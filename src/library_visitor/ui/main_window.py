from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QImage, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from library_visitor.anonymous import AnonymousTracker
from library_visitor.audio import Announcer
from library_visitor.backups import run_daily_backup
from library_visitor.camera import CameraWorker
from library_visitor.config import Settings
from library_visitor.extensions import ExtensionError, Extensions
from library_visitor.gallery import FaceGallery, GalleryFilter, SyncStats, sync_gallery
from library_visitor.licensing import License
from library_visitor.services import VisitorService
from library_visitor.ui.auth_dialog import AdminAuthDialog, external_admin_enabled
from library_visitor.ui.kiosk_window import KioskWindow
from library_visitor.ui.license_dialog import LicenseDialog
from library_visitor.ui.members_page import MembersPage
from library_visitor.ui.register_page import RegisterPage
from library_visitor.ui.report_page import ReportPage
from library_visitor.ui.settings_page import SettingsPage
from library_visitor.ui.theme import role, variant
from library_visitor.ui.visit_page import VisitPage
from library_visitor.ui.widgets import logo_pixmap
from library_visitor.web.registration import RegistrationError, WebRegistration
from library_visitor.web.server import WebRegistrationServer
from library_visitor.web.tls import local_ipv4_addresses

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


GUIDE_PDF = Path(__file__).resolve().parent.parent / "docs" / "Panduan-Penerima-Tamu.pdf"

GALLERY_FILTER_FIELDS = {"gallery_categories", "gallery_prefixes", "gallery_status"}
WEB_FIELDS = {"web_enabled", "web_port", "admin_pin_hash"}


class MainWindow(QMainWindow):
    _gallery_progress = Signal(object)  # SyncStats
    _gallery_done = Signal(object, str)  # SyncStats | None, pesan galat
    _web_saved = Signal()  # dipancarkan dari thread server web

    def __init__(
        self,
        service: VisitorService,
        settings: Settings,
        extensions: Extensions | None = None,
        gallery: FaceGallery | None = None,
        license_: License | None = None,
    ) -> None:
        super().__init__()
        self._license = license_
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

        # Satu pelacak anonim dipakai bersama halaman Kunjungan dan jendela kios
        self.anonymous = AnonymousTracker(
            settings.visit_cooldown_minutes * 60,
            settings.anonymous_same_threshold,
            settings.anonymous_min_frames,
        )
        self.visit_page = VisitPage(
            service,
            settings,
            self.announcer,
            self._extensions.directory,
            anonymous=self.anonymous,
        )
        self._gallery = gallery
        self._gallery_cancel: threading.Event | None = None
        self.register_page = RegisterPage(service, settings, self._extensions.directory, gallery)
        self.members_page = MembersPage(service)
        self.report_page = ReportPage(service, settings)
        self.settings_page = SettingsPage(
            settings,
            self.announcer,
            external_login_available=self._extensions.admin_login is not None,
            license_=license_,
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.visit_page, "Kunjungan")
        self.tabs.addTab(self.register_page, "Registrasi Anggota")
        self.tabs.addTab(self.members_page, "Data Anggota")
        self.tabs.addTab(self.report_page, "Laporan")
        self.tabs.addTab(self.settings_page, "Pengaturan")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        # Tanpa menubar: tombol aplikasi di ujung kanan baris tab, shortcut tetap aktif
        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(12, 2, 16, 2)
        brand_row.setSpacing(10)
        self.brand_logo = QLabel()
        self.brand = role(QLabel(), "brand")
        self.brand_sub = role(QLabel(), "caption")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(self.brand)
        brand_text.addWidget(self.brand_sub)
        brand_row.addWidget(self.brand_logo)
        brand_row.addLayout(brand_text)
        self.tabs.setCornerWidget(brand, Qt.Corner.TopLeftCorner)

        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 4, 12, 4)
        corner_row.setSpacing(6)
        for text, tip, slot, kind in (
            ("Panduan", "Buka panduan pengguna (PDF) · F1", self.open_guide, "ghost"),
            ("Mulai Ulang Kamera", "Sambungkan ulang kamera", self.start_camera, "ghost"),
            ("Kunci", "Kunci tab admin dan kembali ke Kunjungan", self._lock, "ghost"),
            ("Keluar", "Tutup aplikasi", self.close, "danger"),
        ):
            button = variant(QPushButton(text, clicked=slot), kind)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # fokus tetap di input scan kartu
            corner_row.addWidget(button)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        fullscreen = QAction("Layar Penuh", self, triggered=self._toggle_fullscreen)
        fullscreen.setShortcut(QKeySequence("F11"))
        guide = QAction("Panduan", self, triggered=self.open_guide)
        guide.setShortcut(QKeySequence("F1"))
        self.addAction(guide)
        kiosk = QAction("Mode Kios", self, triggered=self.open_kiosk)
        kiosk.setShortcut(QKeySequence("F10"))
        self.addActions([fullscreen, kiosk])

        self.register_page.members_changed.connect(self._on_members_changed)
        self.members_page.members_changed.connect(self._on_members_changed)
        self.visit_page.members_changed.connect(self._update_status)
        self.visit_page.kiosk_requested.connect(self.open_kiosk)
        self.settings_page.saved.connect(self._on_settings_saved)
        for view in (self.visit_page.video, self.register_page.video):
            view.camera_selected.connect(self._select_camera)
        self.settings_page.license_change_requested.connect(self._change_license)
        self._apply_settings()
        self._update_status()

        # Cek backup harian saat mulai lalu tiap jam (aplikasi kios bisa menyala berhari-hari)
        self._backup_timer = QTimer(self, interval=60 * 60 * 1000)
        self._backup_timer.timeout.connect(self._auto_backup)
        self._backup_timer.start()
        QTimer.singleShot(3000, self._auto_backup)

        self.settings_page.gallery_sync_requested.connect(self.start_gallery_sync)
        self.settings_page.gallery_clear_requested.connect(self._clear_gallery)
        self._gallery_progress.connect(self._on_gallery_progress)
        self._gallery_done.connect(self._on_gallery_done)
        self._update_gallery_info()
        QTimer.singleShot(5000, self._auto_gallery_sync)

        self._web = WebRegistrationServer(
            WebRegistration(service, settings, self._extensions.directory),
            settings,
            settings.data_dir / "web",
            on_saved=self._web_saved.emit,
        )
        self._web_saved.connect(self._on_members_changed)
        self._apply_web()

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

    def _select_camera(self, index: int) -> None:
        """Ganti kamera dari tombol di atas tampilan kamera; disimpan seperti di Pengaturan."""
        s = self._settings
        if index == s.camera_index and self._worker is not None:
            return
        s.camera_index = index
        try:
            s.save()
        except OSError as exc:
            log.warning("Pilihan kamera tidak bisa disimpan: %s", exc)
        self.settings_page.refresh()
        self._apply_settings()
        self.start_camera()
        self.statusBar().showMessage(f"Kamera diganti ke #{index}", 5000)

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

    def _authenticate(self, parent: QWidget | None = None, allow_quit: bool = False) -> bool:
        dialog = AdminAuthDialog(
            self._settings, self._extensions.admin_login, parent or self, allow_quit=allow_quit
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.quit_requested:
                QTimer.singleShot(0, self.close)  # closeEvent ikut menutup jendela kios
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
            self._service,
            self._settings,
            self.announcer,
            self._extensions.directory,
            kiosk=True,
            anonymous=self.anonymous,
        )
        page.visit_recorded.connect(self.visit_page.refresh)
        page.members_changed.connect(self._update_status)
        self._kiosk = KioskWindow(page, self._kiosk_exit_allowed)
        self._kiosk.closed.connect(self._on_kiosk_closed)
        self._kiosk.open_on_best_screen(avoid=self)
        self.visit_page.video.show_message("Kamera sedang dipakai Mode Kios")
        self.statusBar().showMessage("Mode Kios aktif (Esc di jendela kios untuk keluar)")

    def _kiosk_exit_allowed(self, parent: QWidget) -> bool:
        return not self._lock_enabled() or self._authenticate(parent, allow_quit=True)

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
        if changed & GALLERY_FILTER_FIELDS and self._gallery is not None:
            self.start_gallery_sync(full=True)
        if changed & WEB_FIELDS:
            self._apply_web()

    # ---------- galeri foto direktori ----------

    def _gallery_available(self) -> bool:
        directory = self._extensions.directory
        return self._gallery is not None and bool(getattr(directory, "supports_faces", False))

    def start_gallery_sync(self, full: bool = False) -> None:
        if not self._gallery_available():
            self.statusBar().showMessage(
                "Galeri foto tidak tersedia: isi DIRECTORY_FACES_URL di .env", 10000
            )
            return
        if self._gallery_cancel is not None:
            self.statusBar().showMessage("Sinkron galeri foto sedang berjalan", 5000)
            return
        self._gallery_cancel = threading.Event()
        self.settings_page.set_gallery_info("Sinkron berjalan...")
        args = (full, GalleryFilter.from_settings(self._settings), self._gallery_cancel)
        threading.Thread(target=self._gallery_worker, args=args, daemon=True).start()

    def _gallery_worker(self, full: bool, gfilter: GalleryFilter, cancel: threading.Event) -> None:
        try:
            stats = sync_gallery(
                self._extensions.directory,
                self._gallery,
                self._settings.models_dir,
                full=full,
                gallery_filter=gfilter,
                progress=self._gallery_progress.emit,
                cancelled=cancel,
            )
        except ExtensionError as exc:
            self._gallery_done.emit(None, str(exc))
        except Exception as exc:  # galat tak terduga tidak boleh mematikan aplikasi
            log.exception("Sinkron galeri foto gagal")
            self._gallery_done.emit(None, str(exc))
        else:
            self._gallery_done.emit(stats, "")

    def _on_gallery_progress(self, stats: SyncStats) -> None:
        self.settings_page.set_gallery_info(
            f"Sinkron berjalan... {stats.total} foto diproses, {stats.added} masuk galeri"
        )

    def _on_gallery_done(self, stats: SyncStats | None, error: str) -> None:
        self._gallery_cancel = None
        if stats is None:
            self.statusBar().showMessage(f"Sinkron galeri foto gagal: {error}", 15000)
        else:
            self.statusBar().showMessage(
                f"Galeri foto: {stats.added} ditambahkan/diperbarui, "
                f"{stats.skipped} tanpa wajah, {stats.filtered} tidak lolos filter",
                10000,
            )
        self._update_gallery_info(error)
        self.register_page.refresh()

    def _clear_gallery(self) -> None:
        if self._gallery is None:
            return
        if self._gallery_cancel is not None:
            self._gallery_cancel.set()
        self._gallery.clear()
        self._update_gallery_info()
        self.register_page.refresh()

    def _update_gallery_info(self, error: str = "") -> None:
        if self._gallery is None:
            self.settings_page.set_gallery_info("Tidak tersedia")
            return
        last = self._gallery.last_synced_at()
        text = f"{len(self._gallery)} wajah"
        if last:
            text += f" · sinkron terakhir {last:%d-%m-%Y %H:%M}"
        if not self._gallery_available():
            text += " · DIRECTORY_FACES_URL belum diisi"
        if error:
            text += f" · galat: {error}"
        self.settings_page.set_gallery_info(text)

    def _auto_gallery_sync(self) -> None:
        if not (self._settings.gallery_auto_sync and self._gallery_available()):
            return
        last = self._gallery.last_synced_at()
        if last is None or datetime.now() - last > timedelta(days=1):
            self.start_gallery_sync(full=False)

    def _apply_settings(self) -> None:
        s = self._settings
        self.setWindowTitle(f"Buku Tamu {s.library_name}")
        self.brand.setText(s.library_name)
        self.brand_sub.setText(s.licensee or "Penerima Tamu")
        self.brand_logo.setPixmap(logo_pixmap(s, 32))
        self._service.matcher.threshold = s.match_threshold
        self._service.cooldown = timedelta(minutes=s.visit_cooldown_minutes)
        self.anonymous.configure(
            s.visit_cooldown_minutes * 60, s.anonymous_same_threshold, s.anonymous_min_frames
        )
        self.announcer.apply_settings()
        for view in (self.visit_page.video, self.register_page.video):
            view.set_current_camera(s.camera_index)
        self.visit_page.apply_settings()
        if self._kiosk is not None:
            self._kiosk.page.apply_settings()

    # ---------- lain-lain ----------

    # ---------- registrasi via web ----------

    def _apply_web(self) -> None:
        s = self._settings
        self._web.stop()
        if not s.web_enabled:
            self.settings_page.set_web_info("Nonaktif")
            return
        if not s.pin_enabled:
            self.settings_page.set_web_info("Tidak aktif: atur PIN admin dulu")
            return
        ips = local_ipv4_addresses()
        try:
            self._web.start(s.web_port, ips=ips)
        except (OSError, RegistrationError) as exc:
            log.warning("Registrasi web gagal dimulai: %s", exc)
            message = f"Gagal aktif di port {s.web_port}: {exc}"
            self.settings_page.set_web_info(message)
            self.statusBar().showMessage(message, 15000)
            return
        urls = [f"https://{ip}:{self._web.port}" for ip in ips] or [
            f"https://localhost:{self._web.port}"
        ]
        self.settings_page.set_web_info("Aktif: " + "  ·  ".join(urls))
        self.statusBar().showMessage(f"Registrasi web aktif: {urls[0]}", 15000)

    # ---------- lisensi ----------

    def _change_license(self) -> None:
        dialog = LicenseDialog(self._settings.data_dir, current=self._license, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_license(dialog.license)
            self.statusBar().showMessage(f"Lisensi aktif: {dialog.license.describe()}", 10000)

    def _set_license(self, lic: License) -> None:
        self._license = lic
        self._settings.licensee = lic.licensee
        self.settings_page.set_license(lic)
        self._apply_settings()

    def _check_license(self) -> None:
        """Aplikasi kios bisa menyala berhari-hari: lisensi kedaluwarsa wajib diperbarui."""
        if self._license is None or not self._license.is_expired():
            return
        log.warning("Lisensi kedaluwarsa: %s", self._license.describe())
        dialog = LicenseDialog(
            self._settings.data_dir,
            current=self._license,
            startup=True,
            reason="Lisensi sudah kedaluwarsa. Masukkan key baru untuk melanjutkan.",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_license(dialog.license)
        else:
            self.close()

    def _auto_backup(self) -> None:
        self._check_license()  # ikut pengecekan per jam
        self._auto_gallery_sync()
        try:
            created = run_daily_backup(self._settings)
        except Exception as exc:  # disk penuh, folder tidak bisa ditulis, dll.
            log.exception("Backup otomatis gagal")
            self.statusBar().showMessage(f"Backup otomatis gagal: {exc}", 15000)
            return
        if created:
            self.statusBar().showMessage(f"Backup otomatis dibuat: {created.name}", 8000)

    def open_guide(self) -> None:
        """Buka panduan PDF (ikut dibundel di installer) dengan penampil PDF bawaan sistem."""
        if not GUIDE_PDF.is_file() or not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(GUIDE_PDF))
        ):
            QMessageBox.information(
                self,
                "Panduan",
                f"Panduan tidak bisa dibuka. File: {GUIDE_PDF}\n"
                "Pastikan ada aplikasi pembuka PDF (mis. browser) di komputer ini.",
            )

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _on_members_changed(self) -> None:
        self.visit_page.refresh()
        self._update_status()

    def _update_status(self) -> None:
        self.statusBar().showMessage(f"Wajah terdaftar: {len(self._service.matcher)}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._gallery_cancel is not None:
            self._gallery_cancel.set()
        if self._kiosk is not None:
            self._kiosk.force_close()
        self.stop_camera()
        self._web.stop()
        self.announcer.shutdown()
        super().closeEvent(event)
