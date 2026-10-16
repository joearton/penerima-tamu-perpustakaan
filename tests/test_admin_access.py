import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402

from library_visitor.__main__ import reset_pin_cli  # noqa: E402
from library_visitor.config import Settings  # noqa: E402
from library_visitor.db import create_session_factory  # noqa: E402
from library_visitor.face import FaceMatcher  # noqa: E402
from library_visitor.services import VisitorService  # noqa: E402
from library_visitor.ui import main_window as main_window_mod  # noqa: E402
from library_visitor.ui.auth_dialog import AdminAuthDialog  # noqa: E402


def quit_button(dialog):
    found = [b for b in dialog.findChildren(QPushButton) if b.text() == "Tutup Aplikasi"]
    return found[0] if found else None


def test_quit_button_only_when_allowed(tmp_path, qt_widgets):
    s = Settings(home=tmp_path)
    s.set_pin("12345")
    normal = AdminAuthDialog(s, None)
    kiosk = AdminAuthDialog(s, None, allow_quit=True)
    qt_widgets(normal)
    qt_widgets(kiosk)
    assert quit_button(normal) is None
    assert quit_button(kiosk) is not None


def test_wrong_pin_with_enter_does_not_quit(tmp_path, qt_widgets):
    s = Settings(home=tmp_path)
    s.set_pin("12345")
    dialog = AdminAuthDialog(s, None, allow_quit=True)
    qt_widgets(dialog)
    dialog.show()
    QTest.keyClicks(dialog.pin, "99999")
    QTest.keyClick(dialog.pin, Qt.Key.Key_Return)
    assert dialog.isVisible() and not dialog.quit_requested
    assert dialog.status.text() == "PIN salah."
    QTimer.singleShot(0, quit_button(dialog).click)
    assert dialog.exec() == QDialog.DialogCode.Rejected and dialog.quit_requested


def test_quit_from_kiosk_dialog_closes_main_window(tmp_path, qt_widgets, monkeypatch):
    s = Settings(home=tmp_path)
    s.set_pin("12345")
    service = VisitorService(create_session_factory(tmp_path / "db.sqlite"), FaceMatcher(0.4), 30)

    class QuitDialog:
        def __init__(self, *args, allow_quit=False, **kwargs):
            assert allow_quit  # hanya dialog keluar kios yang menawarkan tombol tutup
            self.quit_requested = True

        def exec(self):
            return QDialog.DialogCode.Rejected

    window = main_window_mod.MainWindow(service, s)
    qt_widgets(window)
    window.show()
    monkeypatch.setattr(main_window_mod, "AdminAuthDialog", QuitDialog)
    assert window._kiosk_exit_allowed(window) is False
    for _ in range(3):
        QApplication.processEvents()
    assert not window.isVisible()


def test_reset_pin_cli(tmp_path, capsys):
    s = Settings(home=tmp_path)
    assert reset_pin_cli(s, "12a4") == 1
    assert reset_pin_cli(s, "123") == 1
    assert not s.pin_enabled
    assert reset_pin_cli(s, " 12345 ") == 0
    loaded = Settings.load(tmp_path)
    assert loaded.check_pin("12345") and not loaded.check_pin("1234")
    assert "PIN admin diganti" in capsys.readouterr().out
