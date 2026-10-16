import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from library_visitor.camera import FaceResult  # noqa: E402
from library_visitor.config import Settings  # noqa: E402
from library_visitor.db import create_session_factory  # noqa: E402
from library_visitor.extensions import DirectoryPerson  # noqa: E402
from library_visitor.face import FaceMatcher, normalize  # noqa: E402
from library_visitor.gallery import FaceGallery  # noqa: E402
from library_visitor.services import VisitorService  # noqa: E402
from library_visitor.ui import register_page as register_mod  # noqa: E402
from library_visitor.ui.member_completer import MemberCompleter  # noqa: E402
from library_visitor.ui.register_page import RegisterPage  # noqa: E402


def emb(seed):
    return normalize(np.random.default_rng(seed).normal(size=128))


class FakeDirectory:
    label = "Cari di direktori"
    supports_search = True
    supports_faces = True

    def lookup(self, number):
        return None

    def search(self, text, limit=10):
        return [
            DirectoryPerson("2301001", "Siti Aminah", "Mahasiswa", "Informatika", "Aktif"),
            DirectoryPerson("A01", "Duplikat Lokal", "Mahasiswa", "", ""),
        ]


@pytest.fixture
def env(tmp_path, qt_widgets):
    sessions = create_session_factory(tmp_path / "db.sqlite")
    service = VisitorService(sessions, FaceMatcher(0.4), 30)
    service.save_member("A01", "Siti Lokal", "Dosen", unit="Hukum")
    return Settings(home=tmp_path), service, sessions, qt_widgets


def test_completer_merges_local_and_remote(env):
    _, service, _, track = env
    edit = QLineEdit()
    track(edit)
    completer = MemberCompleter(edit, service, FakeDirectory(), "member_no")
    chosen = []
    completer.chosen.connect(lambda p, registered: chosen.append((p.member_no, registered)))
    edit.setText("siti")
    completer._on_edited("siti")
    assert completer._model.rowCount() == 1  # lokal langsung muncul
    edit.setFocus()
    completer._edit.hasFocus = lambda: True  # popup offscreen tidak benar-benar fokus
    completer._on_remote_done("siti", FakeDirectory().search("siti"))
    rows = [completer._model.item(i).text() for i in range(completer._model.rowCount())]
    assert len(rows) == 2 and rows[0].startswith("A01") and rows[1].startswith("2301001")
    completer._on_activated(completer._model.index(1, 0))
    assert chosen == [("2301001", False)]
    completer._on_remote_done("teks lama", [])  # hasil basi diabaikan
    assert completer._model.rowCount() == 2


def test_photo_suggestions_fill_form(env, monkeypatch):
    settings, service, sessions, track = env
    gallery = FaceGallery(sessions)
    target = DirectoryPerson("2501234", "Budi Santoso", "Mahasiswa", "Sistem Informasi", "Aktif")
    gallery.upsert(target, emb(5), "2026-10-01")
    gallery.upsert(DirectoryPerson("2409999", "Lain", "Mahasiswa", "", "Aktif"), emb(6), "")
    page = RegisterPage(service, settings, FakeDirectory(), gallery)
    track(page)
    assert not page.suggest_box.isHidden()
    clock = iter(range(100))
    monkeypatch.setattr(register_mod.time, "monotonic", lambda: float(next(clock)) * 2)
    face = FaceResult((0, 0, 150, 150), normalize(emb(5) + 0.05 * emb(7)), None)
    image = register_mod.QImage(32, 32, register_mod.QImage.Format.Format_RGB888)
    for _ in range(2):  # tebakan diperbarui paling cepat tiap SUGGEST_INTERVAL
        page.on_frame(image, [face])
    assert page._suggest_buttons and "Budi Santoso" in page._suggest_buttons[0].text()
    page._suggest_buttons[0].click()
    assert (page.member_no.text(), page.name.text(), page.unit.text()) == (
        "2501234",
        "Budi Santoso",
        "Sistem Informasi",
    )
    assert page._directory_status == "Aktif"


def test_suggest_box_hidden_without_gallery(env):
    settings, service, sessions, track = env
    page = RegisterPage(service, settings, None, FaceGallery(sessions))
    track(page)
    assert page.suggest_box.isHidden()


def test_lookup_shows_directory_photo(env, monkeypatch):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    settings, service, _, track = env
    image = QImage(40, 50, QImage.Format.Format_RGB32)
    image.fill(0x3366AA)
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    person = DirectoryPerson("2501234", "Budi", "Mahasiswa", "SI", "Aktif", photo=bytes(raw))

    class PhotoDirectory(FakeDirectory):
        def lookup(self, number):
            return person

        def fetch_photo(self, p):
            return p.photo

    page = RegisterPage(service, settings, PhotoDirectory())
    track(page)
    page.member_no.setText("2501234")
    page._lookup_worker("2501234")  # langsung (tanpa thread) agar deterministik
    assert page.name.text() == "Budi"
    assert not page.photo.isHidden() and page.photo.pixmap().width() > 0
    page.member_no.textEdited.emit("2501")
    assert page.photo.isHidden()
