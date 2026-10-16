from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library_visitor.camera import FaceResult
from library_visitor.config import Settings
from library_visitor.extensions import DirectoryPerson, ExtensionError, MemberDirectory
from library_visitor.face import normalize
from library_visitor.services import CATEGORIES, ServiceError, VisitorService
from library_visitor.ui.widgets import VideoView

SAMPLE_INTERVAL = 0.4  # detik antar sampel, agar variasi pose terekam

CONSENT_TEXT = (
    "Anggota menyetujui pengolahan data biometrik wajah untuk keperluan "
    "pencatatan kunjungan perpustakaan (UU No. 27/2022 tentang PDP)."
)


class RegisterPage(QWidget):
    members_changed = Signal()
    _lookup_done = Signal(str, object)  # no. yang dicari, DirectoryPerson | None
    _lookup_failed = Signal(str)

    def __init__(
        self, service: VisitorService, settings: Settings, directory: MemberDirectory | None = None
    ) -> None:
        super().__init__()
        self._service = service
        self._settings = settings
        self._directory = directory
        self._directory_status: str | None = None  # terisi hanya bila data form dari direktori
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="directory")
        self._lookup_done.connect(self._on_lookup_result)
        self._lookup_failed.connect(self._on_lookup_failed)
        self._samples: list[np.ndarray] = []
        self._collecting = False
        self._last_sample = 0.0

        self.video = VideoView()
        self.progress = QProgressBar(maximum=settings.enroll_samples, format="%v / %m sampel")
        self.hint = QLabel('Isi data anggota, lalu klik "Ambil Wajah".')
        self.hint.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.progress)
        left.addWidget(self.hint)

        self.member_no = QLineEdit(placeholderText="Contoh: 2021010123")
        self.member_no.editingFinished.connect(self._load_existing)
        self.member_no.textEdited.connect(self._clear_directory_status)
        self.lookup_btn = QPushButton(
            directory.label if directory else "Cari di direktori", clicked=self._lookup
        )
        if directory is None:
            self.lookup_btn.setEnabled(False)
            self.lookup_btn.setToolTip("Direktori anggota belum dikonfigurasi (lihat .env.example)")
        self.name = QLineEdit()
        self.unit = QLineEdit(placeholderText="Program studi / unit kerja")
        self.directory_label = QLabel("-")
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        self.consent = QCheckBox("Persetujuan data biometrik")
        self.consent.setToolTip(CONSENT_TEXT)
        consent_label = QLabel(CONSENT_TEXT)
        consent_label.setWordWrap(True)
        consent_label.setStyleSheet("color:#666; font-size:11px;")

        self.capture_btn = QPushButton("Ambil Wajah", clicked=self._start_capture)
        self.save_btn = QPushButton("Simpan", clicked=self._save)
        reset_btn = QPushButton("Reset", clicked=self.reset)

        form = QFormLayout()
        no_row = QHBoxLayout()
        no_row.addWidget(self.member_no, 1)
        no_row.addWidget(self.lookup_btn)
        form.addRow("No. Anggota", no_row)
        form.addRow("Nama", self.name)
        form.addRow("Kategori", self.category)
        form.addRow("Prodi/Unit", self.unit)
        form.addRow("Status direktori", self.directory_label)
        form.addRow(self.consent)
        form.addRow(consent_label)

        buttons = QHBoxLayout()
        buttons.addWidget(self.capture_btn)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(reset_btn)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(buttons)
        right.addStretch(1)

        layout = QHBoxLayout(self)
        layout.addLayout(left, 3)
        layout.addLayout(right, 2)

    def _load_existing(self) -> None:
        member = self._service.get_member_by_no(self.member_no.text())
        if member is None:
            if self._directory and self.member_no.text().strip() and not self.name.text():
                self._lookup()
            return
        self.name.setText(member.name)
        self.category.setCurrentText(member.category)
        self.unit.setText(member.unit or "")
        self.directory_label.setText(member.directory_status or "-")
        status = "sudah" if member.face_embedding else "belum"
        self.hint.setText(
            f"Anggota sudah terdaftar; wajah {status} terdaftar. Simpan untuk memperbarui."
        )

    # ---------- direktori anggota ----------

    def _lookup(self) -> None:
        number = self.member_no.text().strip()
        if not self._directory or not number:
            return
        self.lookup_btn.setEnabled(False)
        self.directory_label.setText("Mencari di direktori...")
        self._executor.submit(self._lookup_worker, number)

    def _lookup_worker(self, number: str) -> None:
        try:
            self._lookup_done.emit(number, self._directory.lookup(number))
        except ExtensionError as exc:
            self._lookup_failed.emit(str(exc))

    def _on_lookup_result(self, number: str, person: DirectoryPerson | None) -> None:
        self.lookup_btn.setEnabled(True)
        if number != self.member_no.text().strip():
            return  # nomor sudah diganti selama pencarian
        if person is None:
            self.directory_label.setText("Tidak ditemukan di direktori (isi manual)")
            return
        self.name.setText(person.name)
        self.category.setCurrentText(person.category)
        self.unit.setText(person.unit)
        self._directory_status = person.status
        self.directory_label.setText(f"{person.category} · {person.status or 'status tidak ada'}")

    def _on_lookup_failed(self, message: str) -> None:
        self.lookup_btn.setEnabled(True)
        self.directory_label.setText(message)

    def _clear_directory_status(self) -> None:
        self._directory_status = None

    # ---------- wajah ----------

    def _start_capture(self) -> None:
        if not self.consent.isChecked():
            QMessageBox.warning(self, "Persetujuan", "Centang persetujuan data biometrik dulu.")
            return
        self._samples.clear()
        self._collecting = True
        self.progress.setMaximum(self._settings.enroll_samples)
        self.progress.setValue(0)
        self.hint.setText("Lihat ke kamera dan gerakkan kepala sedikit ke kiri/kanan...")

    def on_frame(self, image: QImage, results: list[FaceResult]) -> None:
        self.video.show_image(image)
        if not self._collecting:
            return
        if len(results) != 1:
            self.hint.setText("Pastikan hanya SATU wajah terlihat di kamera.")
            return
        if results[0].embedding is None:
            self.hint.setText("Wajah terlalu jauh, silakan mendekat.")
            return
        if results[0].spoof:
            self.hint.setText("Wajah terdeteksi dari foto/layar. Gunakan wajah asli.")
            return
        now = time.monotonic()
        if now - self._last_sample < SAMPLE_INTERVAL:
            return
        self._last_sample = now
        self._samples.append(results[0].embedding)
        self.progress.setValue(len(self._samples))
        if len(self._samples) >= self._settings.enroll_samples:
            self._collecting = False
            self.hint.setText('Sampel wajah lengkap. Klik "Simpan".')

    def _save(self) -> None:
        if self._collecting:
            return
        if self._samples and not self.consent.isChecked():
            QMessageBox.warning(self, "Persetujuan", "Persetujuan data biometrik wajib dicentang.")
            return
        if self._samples and not self._confirm_not_duplicate():
            return
        try:
            member = self._service.save_member(
                self.member_no.text(),
                self.name.text(),
                self.category.currentText(),
                self._samples,
                unit=self.unit.text(),
                directory_status=self._directory_status,
            )
        except ServiceError as exc:
            QMessageBox.warning(self, "Gagal", str(exc))
            return
        QMessageBox.information(self, "Tersimpan", f"Data {member.name} berhasil disimpan.")
        self.members_changed.emit()
        self.reset()

    def _confirm_not_duplicate(self) -> bool:
        existing = self._service.get_member_by_no(self.member_no.text())
        mean = normalize(np.mean(self._samples, axis=0))
        best = self._service.matcher.best(mean, exclude=existing.id if existing else None)
        if best is None or best.score < self._service.matcher.threshold:
            return True
        answer = QMessageBox.question(
            self,
            "Wajah mirip anggota lain",
            f"Wajah ini mirip dengan {best.label} (skor {best.score:.2f}).\nTetap simpan?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def reset(self) -> None:
        self._samples.clear()
        self._collecting = False
        self.progress.setValue(0)
        for field in (self.member_no, self.name, self.unit):
            field.clear()
        self._directory_status = None
        self.directory_label.setText("-")
        self.category.setCurrentIndex(0)
        self.consent.setChecked(False)
        self.hint.setText('Isi data anggota, lalu klik "Ambil Wajah".')

    def on_camera_error(self, message: str) -> None:
        self.video.show_message(message)
