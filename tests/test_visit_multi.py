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
    assert announcer.texts[-1].endswith("Siti dan Budi! Selamat datang di Perpustakaan.")


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
