from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from library_visitor import greeting
from library_visitor.audio import TTS_LANGUAGES, Announcer
from library_visitor.backups import backup_dir, list_backups
from library_visitor.config import Settings
from library_visitor.db import backup_database
from library_visitor.licensing import License
from library_visitor.ui.theme import role, variant
from library_visitor.ui.widgets import logo_pixmap

LOGO_FILE = "logo.png"
LOGO_MAX_SIZE = 512  # px, logo disalin & diperkecil ke folder data


def _spin(lo: int, hi: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox(minimum=lo, maximum=hi)
    box.setSuffix(suffix)
    return box


def _dspin(lo: float, hi: float, step: float) -> QDoubleSpinBox:
    return QDoubleSpinBox(minimum=lo, maximum=hi, singleStep=step, decimals=2)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    role(label, "caption")
    return label


class SettingsPage(QWidget):
    saved = Signal(set)  # nama-nama field yang berubah
    gallery_sync_requested = Signal(bool)  # True = sinkron ulang penuh
    gallery_clear_requested = Signal()
    license_change_requested = Signal()

    def __init__(
        self,
        settings: Settings,
        announcer: Announcer,
        external_login_available: bool = False,
        license_: License | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._announcer = announcer
        self._pending_logo: str | None = None  # file logo baru, disalin saat disimpan
        self._remove_logo = False

        # --- Identitas & lisensi ---
        self.library_name = QLineEdit()
        self.library_address = QLineEdit(placeholderText="Alamat lengkap perpustakaan")
        self.library_contact = QLineEdit(placeholderText="Telepon / email / situs web")
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(56, 56)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet(
            "border:1px solid #E2E8F0; border-radius:10px; background:#F8FAFC;"
        )
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_preview)
        logo_row.addWidget(QPushButton("Pilih Logo...", clicked=self._choose_logo))
        logo_row.addWidget(variant(QPushButton("Pakai Bawaan", clicked=self._clear_logo), "ghost"))
        logo_row.addStretch(1)
        self.license_info = QLabel()
        self.license_info.setWordWrap(True)
        self.license_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        license_row = QHBoxLayout()
        license_row.addWidget(self.license_info, 1)
        license_row.addWidget(
            QPushButton("Ganti Lisensi...", clicked=lambda: self.license_change_requested.emit())
        )
        identity = QGroupBox("Identitas Perpustakaan")
        f = QFormLayout(identity)
        f.addRow("Nama perpustakaan", self.library_name)
        f.addRow("Alamat", self.library_address)
        f.addRow("Kontak", self.library_contact)
        f.addRow("Logo", logo_row)
        f.addRow("Lisensi", license_row)
        f.addRow(
            _hint(
                "Nama institusi diambil dari lisensi dan tampil di header, layar kios, dan "
                "laporan Excel. Logo disalin ke folder data aplikasi."
            )
        )
        self.set_license(license_)

        # --- Umum ---
        self.kiosk_on_start = QCheckBox("Buka Mode Kios saat aplikasi dimulai")
        self.kiosk_show_names = QCheckBox("Tampilkan nama pengunjung di layar kios")
        general = QGroupBox("Umum")
        f = QFormLayout(general)
        f.addRow(self.kiosk_on_start)
        f.addRow(self.kiosk_show_names)
        f.addRow(
            _hint(
                "Layar kios menghadap umum. Jika nama tidak ditampilkan, kios hanya "
                "menunjukkan jumlah pengunjung hari ini (sapaan tetap muncul)."
            )
        )

        # --- Kamera & wajah ---
        self.camera_index = QComboBox()
        self.match_threshold = _dspin(0.20, 0.90, 0.01)
        self.detect_score = _dspin(0.50, 0.99, 0.01)
        self.min_face_size = _spin(40, 400, " px")
        self.stable_frames = _spin(1, 30, " frame")
        self.enroll_samples = _spin(1, 20, " sampel")
        self.multi_face = QCheckBox("Catat beberapa wajah sekaligus")
        self.max_faces = _spin(1, 10, " wajah")
        self.antispoof_enabled = QCheckBox("Tolak wajah dari foto/layar (anti-spoofing)")
        self.antispoof_threshold = _dspin(0.30, 0.99, 0.01)
        camera = QGroupBox("Kamera && Pengenalan Wajah")
        f = QFormLayout(camera)
        cam_row = QHBoxLayout()
        cam_row.addWidget(self.camera_index, 1)
        cam_row.addWidget(QPushButton("Pindai", clicked=self._scan_cameras))
        f.addRow("Kamera", cam_row)
        f.addRow("Ambang kemiripan", self.match_threshold)
        f.addRow(_hint("Naikkan bila ada salah kenal; turunkan bila wajah sering tidak dikenali."))
        f.addRow("Skor deteksi minimal", self.detect_score)
        f.addRow("Ukuran wajah minimal", self.min_face_size)
        f.addRow("Konfirmasi wajah", self.stable_frames)
        f.addRow("Sampel registrasi", self.enroll_samples)
        f.addRow(self.multi_face)
        f.addRow("Maks. wajah per frame", self.max_faces)
        f.addRow(
            _hint(
                "Jika dimatikan, hanya wajah terdekat yang dicatat. Wajah yang lebih kecil dari "
                "'Ukuran wajah minimal' (orang jauh di belakang) selalu diabaikan."
            )
        )
        f.addRow(self.antispoof_enabled)
        f.addRow("Skor wajah asli minimal", self.antispoof_threshold)
        f.addRow(
            _hint(
                "Turunkan bila wajah asli sering ditolak (mis. pencahayaan buruk); "
                "naikkan bila foto masih lolos."
            )
        )

        # --- Kunjungan & sapaan ---
        self.cooldown = _spin(0, 24 * 60, " menit")
        self.banner_seconds = _spin(1, 60, " detik")
        self.greeting_template = QLineEdit()
        self.repeat_template = QLineEdit()
        self.guest_template = QLineEdit()
        self.anonymous_template = QLineEdit()
        self.anonymous_enabled = QCheckBox("Hitung wajah tak dikenal sebagai pengunjung anonim")
        self.anonymous_min_frames = _spin(2, 60, " frame")
        self.anonymous_same = _dspin(0.20, 0.90, 0.01)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            "background:#F0FDF4; color:#166534; border:1px solid #BBF7D0;"
            " padding:8px 10px; border-radius:8px;"
        )
        for edit in (self.greeting_template, self.library_name):
            edit.textChanged.connect(self._update_preview)
        greet = QGroupBox("Kunjungan && Sapaan")
        f = QFormLayout(greet)
        f.addRow("Jeda catat ulang", self.cooldown)
        f.addRow("Lama tampil sapaan", self.banner_seconds)
        f.addRow("Sapaan anggota", self.greeting_template)
        f.addRow("Sudah tercatat", self.repeat_template)
        f.addRow("Sapaan tamu", self.guest_template)
        f.addRow("Sapaan anonim", self.anonymous_template)
        f.addRow(self.anonymous_enabled)
        f.addRow("Konfirmasi anonim", self.anonymous_min_frames)
        f.addRow("Kemiripan orang sama", self.anonymous_same)
        f.addRow(
            _hint(
                "Jumlah anonim adalah perkiraan. Wajahnya hanya diingat di memori selama jeda "
                "catat ulang agar tidak terhitung berulang, lalu dibuang; tidak ada nama, foto, "
                "atau embedding yang disimpan. Bila orang yang sama lalu scan kartu atau mengisi "
                "form tamu, catatan anonimnya dihapus otomatis."
            )
        )
        f.addRow("Contoh", self.preview)
        f.addRow(
            _hint(
                "Placeholder: " + ", ".join(f"{k} = {v}" for k, v in greeting.PLACEHOLDERS.items())
            )
        )

        # --- Suara ---
        self.sound_enabled = QCheckBox("Bunyikan notifikasi saat kunjungan tercatat")
        self.sound_file = QLineEdit(placeholderText="(bunyi bawaan)")
        self.tts_enabled = QCheckBox("Ucapkan sapaan (Google Text-to-Speech)")
        self.tts_lang = QComboBox()
        for code, label in TTS_LANGUAGES.items():
            self.tts_lang.addItem(f"{label} ({code})", code)
        self.tts_slow = QCheckBox("Bicara pelan")
        self.speak_repeat = QCheckBox("Ucapkan juga pesan 'sudah tercatat'")
        self.volume = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100)
        volume_label = QLabel()
        self.volume.valueChanged.connect(lambda v: volume_label.setText(f"{v}%"))
        sound = QGroupBox("Suara")
        f = QFormLayout(sound)
        f.addRow(self.sound_enabled)
        file_row = QHBoxLayout()
        file_row.addWidget(self.sound_file, 1)
        file_row.addWidget(QPushButton("Pilih...", clicked=self._choose_sound))
        file_row.addWidget(QPushButton("Bawaan", clicked=self.sound_file.clear))
        f.addRow("File bunyi", file_row)
        f.addRow(self.tts_enabled)
        f.addRow("Bahasa", self.tts_lang)
        f.addRow(self.tts_slow)
        f.addRow(self.speak_repeat)
        vol_row = QHBoxLayout()
        vol_row.addWidget(self.volume, 1)
        vol_row.addWidget(volume_label)
        f.addRow("Volume", vol_row)
        f.addRow(QPushButton("Tes Suara", clicked=self._test_sound))
        f.addRow(
            _hint(
                "gTTS membutuhkan internet dan mengirim teks sapaan (termasuk nama) ke "
                "server Google. Sapaan yang pernah diucapkan disimpan di cache sehingga "
                "tetap bisa diputar saat offline."
            )
        )

        # --- Keamanan & data ---
        self.pin = QLineEdit(placeholderText="Kosongkan = tidak diubah")
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setMaxLength(12)
        self.remove_pin = QCheckBox("Hapus PIN (tab admin tidak dikunci)")
        self.pin_status = QLabel()
        self.admin_usernames = QLineEdit(placeholderText="mis. 0011223344, budi.santoso")
        self.admin_group = QLineEdit(placeholderText="nama grup (opsional)")
        security = QGroupBox("Keamanan && Data")
        f = QFormLayout(security)
        f.addRow("Status", self.pin_status)
        f.addRow("PIN admin baru", self.pin)
        f.addRow(self.remove_pin)
        f.addRow("Admin login eksternal", self.admin_usernames)
        f.addRow("Grup admin", self.admin_group)
        f.addRow(
            _hint(
                "Username atau grup dari login eksternal (OAuth2/OIDC) yang boleh membuka "
                "tab admin."
                + (
                    ""
                    if external_login_available
                    else " Belum aktif: isi variabel OAUTH_* di file .env."
                )
            )
        )
        f.addRow(
            _hint(
                "Jika PIN atau admin login eksternal diatur, tab Registrasi, Data Anggota, "
                "Laporan dan Pengaturan meminta login dan terkunci lagi saat kembali ke tab "
                "Kunjungan."
            )
        )
        self.auto_backup = QCheckBox("Backup otomatis setiap hari")
        self.backup_dir = QLineEdit(placeholderText="(bawaan: data/backups)")
        self.backup_keep = _spin(1, 365, " hari")
        self.backup_status = QLabel()
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.backup_dir, 1)
        dir_row.addWidget(QPushButton("Pilih...", clicked=self._choose_backup_dir))
        f.addRow(self.auto_backup)
        f.addRow("Folder backup", dir_row)
        f.addRow("Simpan backup", self.backup_keep)
        f.addRow("Backup terakhir", self.backup_status)
        f.addRow(
            _hint("Sebaiknya arahkan ke disk/flashdisk lain agar data aman bila disk PC rusak.")
        )
        f.addRow(QPushButton("Backup Manual...", clicked=self._backup))

        # --- Galeri foto direktori ---
        self.photo_suggest = QCheckBox("Tampilkan tebakan identitas saat registrasi")
        self.photo_suggest_count = _spin(1, 10, " tebakan")
        self.photo_suggest_min = _dspin(0.10, 0.90, 0.01)
        self.gallery_auto_sync = QCheckBox("Sinkron otomatis sekali sehari")
        self.gallery_categories = QLineEdit(placeholderText="mis. Mahasiswa (kosong = semua)")
        self.gallery_prefixes = QLineEdit(placeholderText="mis. 23,24,25,26 (kosong = semua)")
        self.gallery_status_filter = QLineEdit(placeholderText="mis. Aktif (kosong = semua)")
        self.gallery_info = QLabel("-")
        self.gallery_info.setWordWrap(True)
        gallery = QGroupBox("Galeri Foto Direktori")
        f = QFormLayout(gallery)
        f.addRow(self.photo_suggest)
        f.addRow("Jumlah tebakan", self.photo_suggest_count)
        f.addRow("Kemiripan minimal", self.photo_suggest_min)
        f.addRow(self.gallery_auto_sync)
        f.addRow("Kategori", self.gallery_categories)
        f.addRow("Awalan nomor", self.gallery_prefixes)
        f.addRow("Status", self.gallery_status_filter)
        f.addRow("Isi galeri", self.gallery_info)
        sync_row = QHBoxLayout()
        sync_row.addWidget(
            QPushButton("Sinkron", clicked=lambda: self.gallery_sync_requested.emit(False))
        )
        sync_row.addWidget(
            QPushButton(
                "Sinkron Ulang Penuh", clicked=lambda: self.gallery_sync_requested.emit(True)
            )
        )
        sync_row.addWidget(
            variant(QPushButton("Hapus Galeri", clicked=self._confirm_clear_gallery), "danger")
        )
        f.addRow(sync_row)
        f.addRow(
            _hint(
                "Foto profil dari direktori hanya diubah menjadi embedding wajah lalu dibuang; "
                "foto tidak disimpan. Mengubah filter memicu sinkron ulang penuh. Butuh "
                "DIRECTORY_FACES_URL di .env."
            )
        )

        # --- Registrasi via web ---
        self.web_enabled = QCheckBox("Aktifkan registrasi anggota via web (HP/laptop di LAN)")
        self.web_port = _spin(1024, 65535)
        self.web_info = QLabel("Nonaktif")
        self.web_info.setWordWrap(True)
        self.web_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        web = QGroupBox("Registrasi via Web (LAN)")
        f = QFormLayout(web)
        f.addRow(self.web_enabled)
        f.addRow("Port", self.web_port)
        f.addRow("Alamat", self.web_info)
        f.addRow(
            _hint(
                "Buka alamat di atas dari HP/laptop yang terhubung ke jaringan yang sama, lalu "
                "login dengan PIN admin (wajib diatur). Sertifikat HTTPS dibuat otomatis, jadi "
                "browser akan menampilkan peringatan sekali: pilih lanjutkan. Hanya perangkat di "
                "jaringan lokal yang diterima; foto wajah tidak disimpan, hanya embedding."
            )
        )

        # --- Tata letak ---
        grid = QGridLayout()
        grid.addWidget(identity, 0, 0)
        grid.addWidget(general, 1, 0)
        grid.addWidget(camera, 2, 0)
        grid.addWidget(security, 3, 0)
        grid.addWidget(greet, 0, 1, 3, 1)
        grid.addWidget(sound, 3, 1)
        grid.addWidget(gallery, 4, 1)
        grid.addWidget(web, 4, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.addLayout(grid)
        inner.addStretch(1)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(content)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(variant(QPushButton("Batalkan Perubahan", clicked=self.refresh), "ghost"))
        save = variant(QPushButton("Simpan Pengaturan", clicked=self._save), "primary")
        save.setDefault(True)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.refresh()

    # ---------- muat & simpan ----------

    def refresh(self) -> None:
        s = self._settings
        self.library_name.setText(s.library_name)
        self.library_address.setText(s.library_address)
        self.library_contact.setText(s.library_contact)
        self._pending_logo = None
        self._remove_logo = False
        self.logo_preview.setPixmap(logo_pixmap(s, 48))
        self.kiosk_on_start.setChecked(s.kiosk_on_start)
        self.kiosk_show_names.setChecked(s.kiosk_show_names)
        self.multi_face.setChecked(s.multi_face)
        self.max_faces.setValue(s.max_faces)
        self.antispoof_enabled.setChecked(s.antispoof_enabled)
        self.antispoof_threshold.setValue(s.antispoof_threshold)
        self.auto_backup.setChecked(s.auto_backup_enabled)
        self.backup_dir.setText(s.backup_dir)
        self.backup_keep.setValue(s.backup_keep)
        self.photo_suggest.setChecked(s.photo_suggest_enabled)
        self.photo_suggest_count.setValue(s.photo_suggest_count)
        self.photo_suggest_min.setValue(s.photo_suggest_min_score)
        self.gallery_auto_sync.setChecked(s.gallery_auto_sync)
        self.gallery_categories.setText(s.gallery_categories)
        self.gallery_prefixes.setText(s.gallery_prefixes)
        self.gallery_status_filter.setText(s.gallery_status)
        existing = list_backups(backup_dir(s))
        self.backup_status.setText(existing[0].name if existing else "belum ada")
        self._scan_cameras()
        self.match_threshold.setValue(s.match_threshold)
        self.detect_score.setValue(s.detect_score)
        self.min_face_size.setValue(s.min_face_size)
        self.stable_frames.setValue(s.stable_frames)
        self.enroll_samples.setValue(s.enroll_samples)
        self.cooldown.setValue(s.visit_cooldown_minutes)
        self.banner_seconds.setValue(s.banner_seconds)
        self.greeting_template.setText(s.greeting_template)
        self.repeat_template.setText(s.repeat_template)
        self.guest_template.setText(s.guest_template)
        self.anonymous_template.setText(s.anonymous_template)
        self.anonymous_enabled.setChecked(s.anonymous_enabled)
        self.anonymous_min_frames.setValue(s.anonymous_min_frames)
        self.anonymous_same.setValue(s.anonymous_same_threshold)
        self.sound_enabled.setChecked(s.sound_enabled)
        self.sound_file.setText(s.sound_file)
        self.tts_enabled.setChecked(s.tts_enabled)
        self.tts_lang.setCurrentIndex(max(0, self.tts_lang.findData(s.tts_lang)))
        self.tts_slow.setChecked(s.tts_slow)
        self.speak_repeat.setChecked(s.speak_repeat)
        self.volume.setValue(s.volume)
        self.pin.clear()
        self.remove_pin.setChecked(False)
        self.web_enabled.setChecked(s.web_enabled)
        self.web_port.setValue(s.web_port)
        self.pin_status.setText("PIN aktif" if s.pin_enabled else "Tanpa PIN")
        self.admin_usernames.setText(s.admin_usernames)
        self.admin_group.setText(s.admin_group)
        self._update_preview()

    def _values(self) -> dict:
        return {
            "library_name": self.library_name.text().strip() or "Perpustakaan",
            "library_address": self.library_address.text().strip(),
            "library_contact": self.library_contact.text().strip(),
            "kiosk_on_start": self.kiosk_on_start.isChecked(),
            "kiosk_show_names": self.kiosk_show_names.isChecked(),
            "multi_face": self.multi_face.isChecked(),
            "max_faces": self.max_faces.value(),
            "antispoof_enabled": self.antispoof_enabled.isChecked(),
            "antispoof_threshold": self.antispoof_threshold.value(),
            "auto_backup_enabled": self.auto_backup.isChecked(),
            "backup_dir": self.backup_dir.text().strip(),
            "backup_keep": self.backup_keep.value(),
            "photo_suggest_enabled": self.photo_suggest.isChecked(),
            "photo_suggest_count": self.photo_suggest_count.value(),
            "photo_suggest_min_score": self.photo_suggest_min.value(),
            "gallery_auto_sync": self.gallery_auto_sync.isChecked(),
            "gallery_categories": self.gallery_categories.text().strip(),
            "gallery_prefixes": self.gallery_prefixes.text().replace(" ", ""),
            "gallery_status": self.gallery_status_filter.text().strip(),
            "camera_index": self.camera_index.currentData(),
            "match_threshold": self.match_threshold.value(),
            "detect_score": self.detect_score.value(),
            "min_face_size": self.min_face_size.value(),
            "stable_frames": self.stable_frames.value(),
            "enroll_samples": self.enroll_samples.value(),
            "visit_cooldown_minutes": self.cooldown.value(),
            "banner_seconds": self.banner_seconds.value(),
            "greeting_template": self.greeting_template.text(),
            "repeat_template": self.repeat_template.text(),
            "guest_template": self.guest_template.text(),
            "anonymous_template": self.anonymous_template.text(),
            "anonymous_enabled": self.anonymous_enabled.isChecked(),
            "anonymous_min_frames": self.anonymous_min_frames.value(),
            "anonymous_same_threshold": self.anonymous_same.value(),
            "sound_enabled": self.sound_enabled.isChecked(),
            "sound_file": self.sound_file.text().strip(),
            "tts_enabled": self.tts_enabled.isChecked(),
            "tts_lang": self.tts_lang.currentData(),
            "tts_slow": self.tts_slow.isChecked(),
            "speak_repeat": self.speak_repeat.isChecked(),
            "volume": self.volume.value(),
            "admin_usernames": self.admin_usernames.text().strip(),
            "admin_group": self.admin_group.text().strip(),
            "web_enabled": self.web_enabled.isChecked(),
            "web_port": self.web_port.value(),
        }

    def _save(self) -> None:
        pin = self.pin.text()
        if pin and (len(pin) < 4 or not pin.isdigit()):
            QMessageBox.warning(self, "PIN", "PIN harus berupa angka, minimal 4 digit.")
            return
        s = self._settings
        pin_after = bool(pin) or (s.pin_enabled and not self.remove_pin.isChecked())
        if self.web_enabled.isChecked() and not pin_after:
            QMessageBox.warning(
                self, "PIN admin", "Registrasi via web butuh PIN admin untuk login. Isi PIN dulu."
            )
            return
        before = s.to_dict()
        try:
            logo = self._store_logo()
        except OSError as exc:
            QMessageBox.warning(self, "Logo", str(exc))
            return
        s.update(self._values())
        if logo is not None:
            s.library_logo = logo
        if self.remove_pin.isChecked():
            s.set_pin("")
        elif pin:
            s.set_pin(pin)
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, "Gagal", f"Pengaturan tidak bisa disimpan:\n{exc}")
            return
        after = s.to_dict()
        changed = {k for k in after if after[k] != before[k]}
        self.refresh()
        self.saved.emit(changed)
        QMessageBox.information(self, "Tersimpan", "Pengaturan disimpan dan langsung diterapkan.")

    # ---------- identitas & lisensi ----------

    def set_web_info(self, text: str) -> None:
        self.web_info.setText(text)

    def set_license(self, lic: License | None) -> None:
        self.license_info.setText(lic.describe() if lic else "Belum ada lisensi aktif")

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih logo perpustakaan", "", "Gambar (*.png *.jpg *.jpeg *.bmp *.svg)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Logo", "File tersebut bukan gambar yang bisa dibaca.")
            return
        self._pending_logo = path
        self._remove_logo = False
        self.logo_preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                48,
                48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _clear_logo(self) -> None:
        self._pending_logo = None
        self._remove_logo = True
        self.logo_preview.setPixmap(QApplication.windowIcon().pixmap(48, 48))

    def _store_logo(self) -> str | None:
        """Nama file logo baru untuk settings ("" = bawaan), atau None bila tidak berubah."""
        if self._remove_logo:
            return ""
        if self._pending_logo is None:
            return None
        image = QImage(self._pending_logo)
        if image.width() > LOGO_MAX_SIZE or image.height() > LOGO_MAX_SIZE:
            image = image.scaled(
                LOGO_MAX_SIZE,
                LOGO_MAX_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        if image.isNull() or not image.save(str(self._settings.data_dir / LOGO_FILE), "PNG"):
            raise OSError("Logo tidak bisa disimpan ke folder data aplikasi.")
        return LOGO_FILE

    # ---------- aksi ----------

    def _scan_cameras(self) -> None:
        current = self.camera_index.currentData()
        if current is None:
            current = self._settings.camera_index
        self.camera_index.clear()
        for i, device in enumerate(QMediaDevices.videoInputs()):
            self.camera_index.addItem(f"#{i}  {device.description()}", i)
        if self.camera_index.findData(current) < 0:
            self.camera_index.addItem(f"#{current}  (tidak terdeteksi)", current)
        self.camera_index.setCurrentIndex(self.camera_index.findData(current))

    def _update_preview(self) -> None:
        self.preview.setText(
            greeting.render(
                self.greeting_template.text(),
                "Siti Aminah",
                "Mahasiswa",
                self.library_name.text().strip() or "Perpustakaan",
            )
        )

    def _choose_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih file bunyi", "", "Audio (*.wav *.mp3 *.ogg)"
        )
        if path:
            self.sound_file.setText(path)

    def _test_sound(self) -> None:
        """Tes dengan nilai di form (belum disimpan), lalu kembalikan pengaturan semula.

        Volume tes tetap berlaku sampai pengaturan disimpan atau aplikasi dibuka ulang.
        """
        s = self._settings
        original = s.to_dict()
        s.update(self._values())
        self._announcer.apply_settings()
        self._announcer.announce(self.preview.text())
        s.update(original)

    def _choose_backup_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pilih folder backup")
        if path:
            self.backup_dir.setText(path)

    def set_gallery_info(self, text: str) -> None:
        self.gallery_info.setText(text)

    def _confirm_clear_gallery(self) -> None:
        answer = QMessageBox.question(
            self, "Hapus galeri", "Hapus semua embedding foto direktori dari PC ini?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.gallery_clear_requested.emit()

    def _backup(self) -> None:
        default = f"library_visitor_backup_{datetime.now():%Y%m%d_%H%M}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Backup database", default, "SQLite (*.db)")
        if not path:
            return
        try:
            backup_database(self._settings.database_path, Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Backup gagal", str(exc))
            return
        QMessageBox.information(self, "Backup selesai", f"Database disalin ke\n{path}")
