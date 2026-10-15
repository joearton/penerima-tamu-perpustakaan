from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
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
from library_visitor.config import Settings
from library_visitor.db import backup_database


def _spin(lo: int, hi: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox(minimum=lo, maximum=hi)
    box.setSuffix(suffix)
    return box


def _dspin(lo: float, hi: float, step: float) -> QDoubleSpinBox:
    return QDoubleSpinBox(minimum=lo, maximum=hi, singleStep=step, decimals=2)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color:#666; font-size:11px;")
    return label


class SettingsPage(QWidget):
    saved = Signal(set)  # nama-nama field yang berubah

    def __init__(
        self, settings: Settings, announcer: Announcer, external_login_available: bool = False
    ) -> None:
        super().__init__()
        self._settings = settings
        self._announcer = announcer

        # --- Umum ---
        self.library_name = QLineEdit()
        general = QGroupBox("Umum")
        f = QFormLayout(general)
        f.addRow("Nama perpustakaan", self.library_name)

        # --- Kamera & wajah ---
        self.camera_index = QComboBox()
        self.match_threshold = _dspin(0.20, 0.90, 0.01)
        self.detect_score = _dspin(0.50, 0.99, 0.01)
        self.min_face_size = _spin(40, 400, " px")
        self.stable_frames = _spin(1, 30, " frame")
        self.enroll_samples = _spin(1, 20, " sampel")
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

        # --- Kunjungan & sapaan ---
        self.cooldown = _spin(0, 24 * 60, " menit")
        self.banner_seconds = _spin(1, 60, " detik")
        self.greeting_template = QLineEdit()
        self.repeat_template = QLineEdit()
        self.guest_template = QLineEdit()
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("background:#eef6ee; padding:6px; border-radius:4px;")
        for edit in (self.greeting_template, self.library_name):
            edit.textChanged.connect(self._update_preview)
        greet = QGroupBox("Kunjungan && Sapaan")
        f = QFormLayout(greet)
        f.addRow("Jeda catat ulang", self.cooldown)
        f.addRow("Lama tampil sapaan", self.banner_seconds)
        f.addRow("Sapaan anggota", self.greeting_template)
        f.addRow("Sudah tercatat", self.repeat_template)
        f.addRow("Sapaan tamu", self.guest_template)
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
        f.addRow(QPushButton("Backup Database...", clicked=self._backup))

        # --- Tata letak ---
        grid = QGridLayout()
        grid.addWidget(general, 0, 0)
        grid.addWidget(camera, 1, 0)
        grid.addWidget(security, 2, 0)
        grid.addWidget(greet, 0, 1, 2, 1)
        grid.addWidget(sound, 2, 1)
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
        buttons.addWidget(QPushButton("Batalkan Perubahan", clicked=self.refresh))
        save = QPushButton("Simpan Pengaturan", clicked=self._save)
        save.setDefault(True)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.refresh()

    # ---------- muat & simpan ----------

    def refresh(self) -> None:
        s = self._settings
        self.library_name.setText(s.library_name)
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
        self.sound_enabled.setChecked(s.sound_enabled)
        self.sound_file.setText(s.sound_file)
        self.tts_enabled.setChecked(s.tts_enabled)
        self.tts_lang.setCurrentIndex(max(0, self.tts_lang.findData(s.tts_lang)))
        self.tts_slow.setChecked(s.tts_slow)
        self.speak_repeat.setChecked(s.speak_repeat)
        self.volume.setValue(s.volume)
        self.pin.clear()
        self.remove_pin.setChecked(False)
        self.pin_status.setText("PIN aktif" if s.pin_enabled else "Tanpa PIN")
        self.admin_usernames.setText(s.admin_usernames)
        self.admin_group.setText(s.admin_group)
        self._update_preview()

    def _values(self) -> dict:
        return {
            "library_name": self.library_name.text().strip() or "Perpustakaan",
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
            "sound_enabled": self.sound_enabled.isChecked(),
            "sound_file": self.sound_file.text().strip(),
            "tts_enabled": self.tts_enabled.isChecked(),
            "tts_lang": self.tts_lang.currentData(),
            "tts_slow": self.tts_slow.isChecked(),
            "speak_repeat": self.speak_repeat.isChecked(),
            "volume": self.volume.value(),
            "admin_usernames": self.admin_usernames.text().strip(),
            "admin_group": self.admin_group.text().strip(),
        }

    def _save(self) -> None:
        pin = self.pin.text()
        if pin and (len(pin) < 4 or not pin.isdigit()):
            QMessageBox.warning(self, "PIN", "PIN harus berupa angka, minimal 4 digit.")
            return
        s = self._settings
        before = s.to_dict()
        s.update(self._values())
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
