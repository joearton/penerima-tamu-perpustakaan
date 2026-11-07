"""Tes regresi untuk bug yang ditemukan saat peninjauan kode."""

import os
import socket
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from library_visitor import greeting  # noqa: E402
from library_visitor.anonymous import MIN_TTL_SECONDS, AnonymousTracker  # noqa: E402
from library_visitor.directory_api import ApiDirectory  # noqa: E402
from library_visitor.extensions import ExtensionError  # noqa: E402
from library_visitor.face import normalize  # noqa: E402
from library_visitor.web.registration import RegistrationError  # noqa: E402
from library_visitor.web.server import LOGIN_MAX_FAILURES, LoginGuard  # noqa: E402


def test_parallel_wrong_pins_still_trigger_lockout():
    """Permintaan paralel tidak boleh melewati batas percobaan PIN."""

    def slow_check(pin):
        time.sleep(0.02)
        return pin == "2468"

    guard = LoginGuard(slow_check)
    results = []

    def attempt(pin):
        try:
            guard.login("192.168.1.50", pin)
            results.append("ok")
        except RegistrationError as exc:
            results.append(exc.status)

    threads = [threading.Thread(target=attempt, args=(f"{i:04d}",)) for i in range(30)]
    threads.append(threading.Thread(target=attempt, args=("2468",)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(401) <= LOGIN_MAX_FAILURES
    assert results.count(429) >= 30 - LOGIN_MAX_FAILURES


def test_dropped_connection_becomes_extension_error():
    """Server yang memutus koneksi tidak boleh membocorkan galat mentah ke UI."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]

    def accept_and_close():
        conn, _ = server.accept()
        conn.recv(1024)
        conn.close()

    threading.Thread(target=accept_and_close, daemon=True).start()
    directory = ApiDirectory(f"http://127.0.0.1:{port}/m/{{nomor}}/", "k", "s", timeout=5)
    try:
        with pytest.raises(ExtensionError, match="Tidak bisa terhubung"):
            directory.lookup("123")
    finally:
        server.close()


def test_zero_cooldown_does_not_recount_same_anonymous_face():
    tracker = AnonymousTracker(ttl_seconds=0, same_threshold=0.4, min_frames=3)
    assert tracker.ttl == MIN_TTL_SECONDS
    face = normalize(np.random.default_rng(1).normal(size=128))
    recorded = 0
    for frame in range(300):  # 10 detik @ 30 fps, orang yang sama
        now = frame / 30
        for ready in tracker.observe([face], now):
            tracker.attach(ready, visit_id=frame, now=now)  # seperti VisitPage
            recorded += 1
    assert recorded == 1


@pytest.mark.parametrize("template", ["{nama.depan}", "{nama[depan]}", "{salam", "{0}"])
def test_bad_greeting_template_does_not_raise(template):
    assert greeting.render(template, "Siti", "Umum", "Lokasi") == template


def test_camera_worker_stop_before_start_is_honored(tmp_path):
    from library_visitor.camera import CameraWorker
    from library_visitor.face import FaceMatcher

    worker = CameraWorker(0, tmp_path, FaceMatcher(0.4), 0.85, 60)
    assert worker.stop(100)  # belum berjalan: langsung selesai
    assert worker._stop_event.is_set()  # run() berikutnya akan langsung keluar


def test_open_kiosk_relocks_admin_tabs(tmp_path, qt_widgets, monkeypatch):
    from library_visitor.config import Settings
    from library_visitor.db import create_session_factory
    from library_visitor.face import FaceMatcher
    from library_visitor.services import VisitorService
    from library_visitor.ui import main_window as mw

    s = Settings(home=tmp_path)
    s.set_pin("12345")
    service = VisitorService(create_session_factory(tmp_path / "db.sqlite"), FaceMatcher(0.4), 30)
    window = mw.MainWindow(service, s)
    qt_widgets(window)
    window._unlocked = True
    window.tabs.setCurrentIndex(4)  # admin membuka Pengaturan

    class FakeKiosk:
        closed = type("Sig", (), {"connect": lambda self, f: None})()

        def __init__(self, *args):
            pass

        def open_on_best_screen(self, avoid=None):
            pass

        def force_close(self):
            pass

    monkeypatch.setattr(mw, "KioskWindow", FakeKiosk)
    window.open_kiosk()
    assert window.tabs.currentIndex() == 0 and not window._unlocked
    window._kiosk = None


def _jitter(seed, noise):
    rng = np.random.default_rng
    return normalize(rng(seed).normal(size=128) + 0.08 * rng(noise).normal(size=128))


def test_recognized_member_not_counted_as_anonymous_later():
    """Anggota dikenali, lalu skornya turun beberapa frame: jangan dihitung anonim."""
    tracker = AnonymousTracker(ttl_seconds=1800, same_threshold=0.4, min_frames=3)
    assert tracker.mark_known([_jitter(5, 50)], now=0.0) == []
    ready = []
    for i in range(20):  # skor turun di bawah ambang pengenalan, wajah tetap sama
        ready += tracker.observe([_jitter(5, 60 + i)], now=0.1 * (i + 1))
    assert ready == []


def test_anonymous_record_dropped_when_member_recognized_soon_after():
    """Terhitung anonim dulu, lalu dikenali sebagai anggota: catatan anonim dihapus."""
    tracker = AnonymousTracker(ttl_seconds=1800, same_threshold=0.4, min_frames=2)
    ready = []
    for i in range(2):
        ready += tracker.observe([_jitter(7, 70 + i)], now=0.1 * i)
    assert len(ready) == 1
    tracker.attach(ready[0], visit_id=41, now=0.2)
    assert tracker.mark_known([_jitter(7, 80)], now=5.0) == [41]
    assert tracker.mark_known([_jitter(7, 81)], now=6.0) == []  # sekali saja
    # Wajah anonim yang tercatat lama sebelumnya tidak dihapus (bisa jadi orang lain)
    old = AnonymousTracker(ttl_seconds=1800, same_threshold=0.4, min_frames=2)
    first = []
    for i in range(2):
        first += old.observe([_jitter(8, 90 + i)], now=0.1 * i)
    old.attach(first[0], visit_id=42, now=0.2)
    assert old.mark_known([_jitter(8, 95)], now=600.0) == []
