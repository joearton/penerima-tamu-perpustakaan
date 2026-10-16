from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QImage, QKeySequence
from PySide6.QtWidgets import QDialog, QMainWindow, QTabWidget, QWidget

from library_visitor.audio import Announcer
from library_visitor.backups import run_daily_backup
from library_visitor.camera import CameraWorker
from library_visitor.config import Settings
from library_visitor.extensions import Extensions
from library_visitor.services import VisitorService
from library_visitor.ui.auth_dialog import AdminAuthDialog, external_admin_enabled
from library_visitor.ui.kiosk_window import KioskWindow
from library_visitor.ui.members_page import MembersPage
from library_visitor.ui.register_page import RegisterPage
from library_visitor.ui.report_page import ReportPage
from library_visitor.ui.settings_page import SettingsPage
from library_visitor.ui.visit_page import VisitPage

log = logging.getLogger(__name__)

# Perubahan field ini membutuhkan restart thread kamera
CAMERA_FIELDS = {
    "camera_index",
    "detect_score",
    "min_face_size",
    "antispoof_enabled",
    "antispoof_threshold",
    "max_faces",
}


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
        self._kiosk: KioskWindow | None = None
        self._unlocked = False
        self._current_tab = 0
        self.resize(1280, 800)

        self.announcer = Announcer(settings)
        self.announcer.failed.connect(lambda msg: self.statusBar().showMessage(msg, 8000))

        self.visit_page = VisitPage(service, settings, self.announcer, self._extensions.directory)
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
        kiosk = QAction("Mode Kios (layar penuh pencatatan)", self, triggered=self.open_kiosk)
        kiosk.setShortcut(QKeySequence("F10"))
        app_menu.addAction(kiosk)
        app_menu.addAction(QAction("Kunci Admin", self, triggered=self._lock))
        app_menu.addSeparator()
        app_menu.addAction(QAction("Keluar", self, triggered=self.close))

        self.register_page.members_changed.connect(self._on_members_changed)
        self.members_page.members_changed.connect(self._on_members_changed)
        self.visit_page.members_changed.connect(self._update_status)
        self.visit_page.kiosk_requested.connect(self.open_kiosk)
        self.settings_page.saved.connect(self._on_settings_saved)
        self._apply_settings()
        self._update_status()

        # Cek backup harian saat mulai lalu tiap jam (aplikasi kios bisa menyala berhari-hari)
        self._backup_timer = QTimer(self, interval=60 * 60 * 1000)
        self._backup_timer.timeout.connect(self._auto_backup)
        self._backup_timer.start()
        QTimer.singleShot(3000, self._auto_backup)

    # ---------- kamera ----------

    def start_camera(self) -> None:
        self.stop_camera()
        s = self._settings
        self._worker = CameraWorker(
            s.camera_index,
            s.models_dir,
            self._service.matcher,
            s.detect_score,
            s.min_face_size,
            max_faces=s.max_faces,
            antispoof_threshold=s.antispoof_threshold if s.antispoof_enabled else None,
        )
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.failed.connect(self._on_camera_error)
        self._worker.start()

    def stop_camera(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

    def _on_frame(self, image: QImage, results: list) -> None:
        # Selama mode kios aktif, hanya jendela kios yang memproses frame (mencegah catat ganda)
        page = self._kiosk.page if self._kiosk is not None else self.tabs.currentWidget()
        if hasattr(page, "on_frame"):
            page.on_frame(image, results)

    def _on_camera_error(self, message: str) -> None:
        log.warning("Kamera: %s", message)
        self.visit_page.on_camera_error(message)
        self.register_page.on_camera_error(message)
        if self._kiosk is not None:
            self._kiosk.page.on_camera_error(message)
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

    def _authenticate(self, parent: QWidget | None = None) -> bool:
        dialog = AdminAuthDialog(self._settings, self._extensions.admin_login, parent or self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._unlocked = True
        self.statusBar().showMessage(f"Mode admin: {dialog.admin_name}", 10000)
        return True

    def _lock(self) -> None:
        self.tabs.setCurrentIndex(0)
        self._unlocked = False

    # ---------- mode kios ----------

    def open_kiosk(self) -> None:
        if self._kiosk is not None:
            self._kiosk.raise_()
            self._kiosk.activateWindow()
            return
        page = VisitPage(
            self._service, self._settings, self.announcer, self._extensions.directory, kiosk=True
        )
        page.visit_recorded.connect(self.visit_page.refresh)
        page.members_changed.connect(self._update_status)
        self._kiosk = KioskWindow(page, self._kiosk_exit_allowed)
        self._kiosk.closed.connect(self._on_kiosk_closed)
        self._kiosk.open_on_best_screen(avoid=self)
        self.visit_page.video.show_message("Kamera sedang dipakai Mode Kios")
        self.statusBar().showMessage("Mode Kios aktif (Esc di jendela kios untuk keluar)")

    def _kiosk_exit_allowed(self, parent: QWidget) -> bool:
        return not self._lock_enabled() or self._authenticate(parent)

    def _on_kiosk_closed(self) -> None:
        self._kiosk.deleteLater()
        self._kiosk = None
        self.visit_page.refresh()
        self._update_status()

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
        if self._kiosk is not None:
            self._kiosk.page.apply_settings()

    # ---------- lain-lain ----------

    def _auto_backup(self) -> None:
        try:
            created = run_daily_backup(self._settings)
        except Exception as exc:  # disk penuh, folder tidak bisa ditulis, dll.
            log.exception("Backup otomatis gagal")
            self.statusBar().showMessage(f"Backup otomatis gagal: {exc}", 15000)
            return
        if created:
            self.statusBar().showMessage(f"Backup otomatis dibuat: {created.name}", 8000)

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _on_members_changed(self) -> None:
        self.visit_page.refresh()
        self._update_status()

    def _update_status(self) -> None:
        self.statusBar().showMessage(f"Wajah terdaftar: {len(self._service.matcher)}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._kiosk is not None:
            self._kiosk.force_close()
        self.stop_camera()
        self.announcer.shutdown()
        super().closeEvent(event)
