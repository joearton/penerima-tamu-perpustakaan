import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from library_visitor.camera import FaceResult  # noqa: E402
from library_visitor.config import Settings  # noqa: E402
from library_visitor.db import create_session_factory  # noqa: E402
from library_visitor.face import FaceMatcher, normalize  # noqa: E402
from library_visitor.services import VisitorService  # noqa: E402
from library_visitor.ui.visit_page import VisitPage  # noqa: E402


class SilentAnnouncer:
    def __init__(self):
        self.texts = []

    def announce(self, text, speak=True, chime=True):
        self.texts.append(text)


def emb(seed):
    return normalize(np.random.default_rng(seed).normal(size=128))


@pytest.fixture
def setup(tmp_path, qt_widgets):
    settings = Settings(home=tmp_path)
    service = VisitorService(create_session_factory(":memory:"), FaceMatcher(0.4), 30)
    ids = [
        service.save_member(f"A{i}", name, "Mahasiswa", [emb(i)]).id
        for i, name in enumerate(["Siti Aminah", "Budi Santoso", "Rina Wati"])
    ]
    announcer = SilentAnnouncer()
    page = VisitPage(service, settings, announcer)
    qt_widgets(page)
    return settings, service, page, announcer, ids


def frame(service, seeds, spoof=()):
    results = []
    for seed in seeds:
        e = emb(seed)
        is_spoof = seed in spoof
        match = None if is_spoof else service.matcher.match(e)
        results.append(FaceResult((0, 0, 120, 120), e, match, 0.9, spoof=is_spoof))
    return results


IMG = QImage(64, 48, QImage.Format.Format_RGB888)


def test_multiple_faces_recorded_together(setup):
    settings, service, page, announcer, _ = setup
    for _ in range(settings.stable_frames):
        page.on_frame(IMG, frame(service, [0, 1]))
    assert page.today.count.text() == "2"
    assert announcer.texts[-1].endswith("Siti dan Budi! Selamat datang di Instansi Kami.")


def test_streak_is_per_person(setup):
    settings, service, page, announcer, _ = setup
    # Rina hanya muncul sebentar (kurang dari N frame) lalu pergi: tidak tercatat
    for i in range(settings.stable_frames):
        page.on_frame(IMG, frame(service, [0, 2] if i < 2 else [0]))
    assert page.today.count.text() == "1"
    assert "Siti!" in announcer.texts[-1]


def test_single_face_mode_and_spoof(setup):
    settings, service, page, announcer, _ = setup
    settings.multi_face = False
    for _ in range(settings.stable_frames):
        page.on_frame(IMG, frame(service, [1, 0]))  # hanya yang terdekat (pertama)
    assert page.today.count.text() == "1" and "Budi!" in announcer.texts[-1]
    settings.multi_face = True
    for _ in range(settings.stable_frames):
        page.on_frame(IMG, frame(service, [2], spoof={2}))  # wajah palsu tidak dicatat
    assert page.today.count.text() == "1"
    assert "tidak terdeteksi asli" in page.banner.text()


def test_manual_input_autocompletes_names_except_in_kiosk(setup, qt_widgets):
    settings, service, page, announcer, _ = setup
    completer = page.member_no.completer()
    assert completer is not None
    page.member_no.textEdited.emit("budi")
    assert completer.model().index(0, 0).data(completer.completionRole()) == "A1"
    kiosk = VisitPage(service, settings, announcer, kiosk=True)
    qt_widgets(kiosk)
    assert kiosk.member_no.completer() is None  # nama anggota lain tidak tampil di layar publik


def test_camera_and_form_panels_are_resizable_and_remembered(setup, qt_widgets):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSplitter

    settings, service, page, announcer, _ = setup
    splitter = page.findChild(QSplitter)
    assert splitter is not None and splitter.count() == 2
    splitter.setSizes([300, 700])
    splitter.splitterMoved.emit(300, 1)
    splitter.findChild(QTimer).timeout.emit()  # simpan tanpa menunggu jeda
    saved = Settings.load(settings.home).splitter_sizes["visit"]
    assert saved == splitter.sizes() and len(saved) == 2
    reopened = VisitPage(service, settings, announcer)
    qt_widgets(reopened)
    assert reopened.findChild(QSplitter).sizes() == saved


def test_camera_switch_button_outside_kiosk_only(setup, qt_widgets):
    settings, service, page, announcer, _ = setup
    assert page.video.switch_button is not None
    kiosk = VisitPage(service, settings, announcer, kiosk=True)
    qt_widgets(kiosk)
    assert kiosk.video.switch_button is None  # pengunjung tidak bisa mengganti kamera
    chosen = []
    page.video.camera_selected.connect(chosen.append)
    menu = page.video.switch_button.menu()
    page.video._fill_camera_menu(menu)
    actions = [a for a in menu.actions() if a.isEnabled()]
    if actions:  # mesin CI mungkin tanpa kamera
        actions[-1].trigger()
        assert chosen == [len(actions) - 1]
