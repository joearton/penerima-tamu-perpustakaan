"""Jendela layar penuh khusus pencatatan kunjungan (mode kios)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout, QWidget

from library_visitor.ui.visit_page import VisitPage


class KioskWindow(QWidget):
    """Membungkus VisitPage(kiosk=True). Keluar lewat Esc dan wajib lolos `authenticate`."""

    closed = Signal()

    def __init__(self, page: VisitPage, authenticate: Callable[[QWidget], bool]) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Mode Kios - Penerima Tamu")
        self.page = page
        self._authenticate = authenticate
        self._allow_close = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.request_exit)

    def open_on_best_screen(self, avoid: QWidget | None = None) -> None:
        """Pakai monitor lain bila ada (mis. monitor menghadap pengunjung)."""
        screens = QGuiApplication.screens()
        current = avoid.screen() if avoid is not None else None
        others = [s for s in screens if s is not current]
        screen = others[0] if others else (current or QGuiApplication.primaryScreen())
        # setScreen (bukan setGeometry) agar juga berfungsi di Wayland
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.page.member_no.setFocus()

    def request_exit(self) -> None:
        if self._authenticate(self):
            self.force_close()
        else:
            self.page.member_no.setFocus()

    def force_close(self) -> None:
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close:
            # Alt+F4 dsb. diperlakukan seperti Esc: perlu otorisasi admin
            event.ignore()
            QTimer.singleShot(0, self.request_exit)
            return
        self.closed.emit()
        super().closeEvent(event)
