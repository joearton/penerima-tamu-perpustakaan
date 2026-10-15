from __future__ import annotations

from datetime import timedelta

from PySide6.QtGui import QAction, QCloseEvent, QImage, QKeySequence
from PySide6.QtWidgets import QDialog, QMainWindow, QTabWidget

from library_visitor.audio import Announcer
from library_visitor.camera import CameraWorker
from library_visitor.config import Settings
from library_visitor.extensions import Extensions
from library_visitor.services import VisitorService
from library_visitor.ui.auth_dialog import AdminAuthDialog, external_admin_enabled
from library_visitor.ui.members_page import MembersPage
from library_visitor.ui.register_page import RegisterPage
from library_visitor.ui.report_page import ReportPage
from library_visitor.ui.settings_page import SettingsPage
from library_visitor.ui.visit_page import VisitPage

# Perubahan field ini membutuhkan restart thread kamera
CAMERA_FIELDS = {"camera_index", "detect_score", "min_face_size"}


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: VisitorService,
        settings: Settings,
        extensions: Extensions | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._settings = settings
        self._extensions = extensions or Extensions()
        self._worker: CameraWorker | None = None
        self._unlocked = False
        self._current_tab = 0
        self.resize(1280, 800)

        self.announcer = Announcer(settings)
        self.announcer.failed.connect(lambda msg: self.statusBar().showMessage(msg, 8000))

        self.visit_page = VisitPage(service, settings, self.announcer)
        self.register_page = RegisterPage(service, settings, self._extensions.directory)
        self.members_page = MembersPage(service)
        self.report_page = ReportPage(service)
        self.settings_page = SettingsPage(
            settings,
            self.announcer,
            external_login_available=self._extensions.admin_login is not None,
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(self.visit_page, "Kunjungan")
        self.tabs.addTab(self.register_page, "Registrasi Anggota")
        self.tabs.addTab(self.members_page, "Data Anggota")
        self.tabs.addTab(self.report_page, "Laporan")
        self.tabs.addTab(self.settings_page, "Pengaturan")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        menu = self.menuBar()
        app_menu = menu.addMenu("Aplikasi")
        app_menu.addAction(QAction("Mulai Ulang Kamera", self, triggered=self.start_camera))
        fullscreen = QAction("Layar Penuh", self, triggered=self._toggle_fullscreen)
        fullscreen.setShortcut(QKeySequence("F11"))
        app_menu.addAction(fullscreen)
        app_menu.addAction(QAction("Kunci Admin", self, triggered=self._lock))
        app_menu.addSeparator()
        app_menu.addAction(QAction("Keluar", self, triggered=self.close))

        self.register_page.members_changed.connect(self._on_members_changed)
        self.members_page.members_changed.connect(self._on_members_changed)
        self.settings_page.saved.connect(self._on_settings_saved)
        self._apply_settings()
        self._update_status()

    # ---------- kamera ----------

    def start_camera(self) -> None:
        self.stop_camera()
        s = self._settings
        self._worker = CameraWorker(
            s.camera_index, s.models_dir, self._service.matcher, s.detect_score, s.min_face_size
        )
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.failed.connect(self._on_camera_error)
        self._worker.start()

    def stop_camera(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

    def _on_frame(self, image: QImage, results: list) -> None:
        page = self.tabs.currentWidget()
        if hasattr(page, "on_frame"):
            page.on_frame(image, results)

    def _on_camera_error(self, message: str) -> None:
        self.visit_page.on_camera_error(message)
        self.register_page.on_camera_error(message)
        self.statusBar().showMessage(message)

    # ---------- tab & PIN admin ----------

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self._unlocked = False  # kembali ke mode kios
        elif self._lock_enabled() and not self._unlocked and not self._authenticate():
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self._current_tab)
            self.tabs.blockSignals(False)
            return
        self._current_tab = index
        page = self.tabs.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _lock_enabled(self) -> bool:
        return self._settings.pin_enabled or external_admin_enabled(
            self._settings, self._extensions.admin_login
        )

    def _authenticate(self) -> bool:
        dialog = AdminAuthDialog(self._settings, self._extensions.admin_login, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._unlocked = True
        self.statusBar().showMessage(f"Mode admin: {dialog.admin_name}", 10000)
        return True

    def _lock(self) -> None:
        self.tabs.setCurrentIndex(0)
        self._unlocked = False

    # ---------- pengaturan ----------

    def _on_settings_saved(self, changed: set) -> None:
        self._apply_settings()
        if changed & CAMERA_FIELDS:
            self.start_camera()

    def _apply_settings(self) -> None:
        s = self._settings
        self.setWindowTitle(f"Buku Tamu {s.library_name}")
        self._service.matcher.threshold = s.match_threshold
        self._service.cooldown = timedelta(minutes=s.visit_cooldown_minutes)
        self.announcer.apply_settings()
        self.visit_page.apply_settings()

    # ---------- lain-lain ----------

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _on_members_changed(self) -> None:
        self.visit_page.refresh()
        self._update_status()

    def _update_status(self) -> None:
        self.statusBar().showMessage(f"Wajah terdaftar: {len(self._service.matcher)}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_camera()
        self.announcer.shutdown()
        super().closeEvent(event)
