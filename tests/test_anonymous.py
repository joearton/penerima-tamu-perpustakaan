from datetime import date

import numpy as np
import pytest
from PySide6.QtGui import QImage

from library_visitor.anonymous import AnonymousTracker
from library_visitor.camera import FaceResult
from library_visitor.config import Settings
from library_visitor.db import create_session_factory
from library_visitor.face import FaceMatcher, normalize
from library_visitor.reports import visits_dataframe
from library_visitor.services import VisitorService
from library_visitor.ui import visit_page as visit_mod
from library_visitor.ui.visit_page import VisitPage


def emb(seed):
    return normalize(np.random.default_rng(seed).normal(size=128))


def jitter(seed, noise_seed):
    return normalize(emb(seed) + 0.08 * emb(noise_seed))


def run(tracker, frames, start=0.0):
    """frames: daftar daftar-embedding; mengembalikan embedding yang siap dicatat."""
    ready = []
    for i, embeddings in enumerate(frames):
        ready += tracker.observe(embeddings, start + i * 0.1)
    return ready


def test_needs_consecutive_frames_and_counts_once():
    t = AnonymousTracker(ttl_seconds=60, same_threshold=0.4, min_frames=3)
    assert run(t, [[jitter(1, 10)], [jitter(1, 11)]]) == []  # baru 2 frame
    assert run(t, [[]]) == []  # hilang: kandidat gugur
    ready = run(t, [[jitter(1, 12)], [jitter(1, 13)], [jitter(1, 14)]], start=1)
    assert len(ready) == 1
    t.attach(ready[0], visit_id=7, now=1.3)
    # Orang yang sama terlihat lagi: tidak dihitung ulang selama ttl
    assert run(t, [[jitter(1, 15)]] * 5, start=10) == []
    # Orang lain dihitung terpisah, dua orang sekaligus dalam satu frame
    both = run(t, [[jitter(2, 20), jitter(3, 30)]] * 3, start=20)
    assert len(both) == 2


def test_ttl_expiry_allows_recount():
    t = AnonymousTracker(ttl_seconds=5, same_threshold=0.4, min_frames=2)
    ready = run(t, [[jitter(1, 10)]] * 2)
    t.attach(ready[0], 1, now=0.2)
    assert run(t, [[jitter(1, 11)]] * 2, start=100) != []  # sudah lewat ttl


def test_claim_recent_returns_recorded_visit_and_blocks_future():
    t = AnonymousTracker(ttl_seconds=60, same_threshold=0.4, min_frames=2)
    ready = run(t, [[jitter(1, 10)]] * 2)
    t.attach(ready[0], 42, now=0.2)
    assert t.claim_recent(now=5) == 42  # orang di depan kamera ternyata scan kartu
    assert run(t, [[jitter(1, 11)]] * 3, start=6) == []  # tidak dihitung anonim lagi
    assert t.claim_recent(now=500) is None  # di luar jendela waktu


def test_claim_before_anonymous_recorded():
    t = AnonymousTracker(ttl_seconds=60, same_threshold=0.4, min_frames=5)
    run(t, [[jitter(1, 10)]] * 2)  # masih dikonfirmasi
    assert t.claim_recent(now=1) is None
    assert run(t, [[jitter(1, 11)]] * 6, start=2) == []


class SilentAnnouncer:
    def __init__(self):
        self.texts = []

    def announce(self, text, speak=True, chime=True):
        self.texts.append(text)


@pytest.fixture
def page(tmp_path, qt_widgets, monkeypatch):
    settings = Settings(home=tmp_path)
    settings.update({"anonymous_min_frames": 3, "library_name": "Perpus"})
    service = VisitorService(create_session_factory(":memory:"), FaceMatcher(0.4), 30)
    service.save_member("A01", "Siti Aminah", "Mahasiswa")  # anggota tanpa wajah terdaftar
    tracker = AnonymousTracker(1800, settings.anonymous_same_threshold, 3)
    announcer = SilentAnnouncer()
    p = VisitPage(service, settings, announcer, anonymous=tracker)
    qt_widgets(p)
    clock = {"t": 1000.0}
    monkeypatch.setattr(visit_mod.time, "monotonic", lambda: clock["t"])
    return p, service, announcer, clock


IMG = QImage(32, 24, QImage.Format.Format_RGB888)


def unknown_face(seed, noise):
    return FaceResult((0, 0, 120, 120), jitter(seed, noise), None, 0.95)


def test_unknown_face_recorded_as_anonymous_once(page):
    p, service, announcer, clock = page
    for i in range(6):
        clock["t"] += 0.1
        p.on_frame(IMG, [unknown_face(1, 50 + i)])
    df = visits_dataframe(service, date.today(), date.today())
    assert list(df["Kategori"]) == ["Anonim"] and list(df["Nama"]) == ["Pengunjung anonim"]
    assert announcer.texts[-1].endswith("Selamat datang di Perpus.")
    assert "1 anonim" in p.today.summary.text()


def test_card_scan_merges_anonymous_visit(page):
    p, service, _, clock = page
    for i in range(3):
        clock["t"] += 0.1
        p.on_frame(IMG, [unknown_face(1, 60 + i)])
    assert p.today.count.text() == "1"  # tercatat anonim dulu
    clock["t"] += 5
    p.member_no.setText("A01")
    p._record_manual()  # orang yang sama lalu scan kartu
    df = visits_dataframe(service, date.today(), date.today())
    assert list(df["Nama"]) == ["Siti Aminah"]  # catatan anonim dihapus, tidak ganda
    for i in range(5):  # tetap di depan kamera: tidak dihitung anonim lagi
        clock["t"] += 0.1
        p.on_frame(IMG, [unknown_face(1, 70 + i)])
    assert p.today.count.text() == "1"


def test_spoof_and_disabled_not_counted(page):
    p, service, _, clock = page
    spoof = FaceResult((0, 0, 120, 120), emb(5), None, 0.1, spoof=True)
    for _ in range(5):
        clock["t"] += 0.1
        p.on_frame(IMG, [spoof])
    p._settings.anonymous_enabled = False
    for i in range(5):
        clock["t"] += 0.1
        p.on_frame(IMG, [unknown_face(2, 80 + i)])
    assert p.today.count.text() == "0"
