"""Dialog aktivasi / penggantian key lisensi."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library_visitor.licensing import License, LicenseError, save_license, validate_license
from library_visitor.ui.theme import role, variant


class LicenseDialog(QDialog):
    """`startup=True`: aplikasi belum boleh dipakai, tombol tolak berarti keluar aplikasi."""

    def __init__(
        self,
        data_dir: Path,
        current: License | None = None,
        startup: bool = False,
        reason: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = data_dir
        self.license: License | None = None
        self.setWindowTitle("Aktivasi Lisensi" if startup else "Lisensi")
        self.setMinimumWidth(560)

        title = role(QLabel("Aktivasi Penerima Tamu Perpustakaan"), "title")
        intro = role(
            QLabel(
                "Masukkan key lisensi dari penyedia aplikasi. Key memuat nama institusi "
                "pemegang lisensi dan masa berlakunya; verifikasi dilakukan offline."
            ),
            "muted",
        )
        intro.setWordWrap(True)

        self.current = QLabel(
            f"Lisensi saat ini: {current.describe()}" if current else "Belum ada lisensi aktif."
        )
        self.current.setWordWrap(True)
        role(self.current, "callout" if current else "muted")
        if current:
            self.current.setStyleSheet("font-size:13px;")

        self.key_edit = QPlainTextEdit(placeholderText="PTP1.xxxxxxxx.xxxxxxxx")
        self.key_edit.setFixedHeight(96)
        self.key_edit.textChanged.connect(lambda: self.status.clear())

        self.status = QLabel(reason)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#DC2626; font-weight:600;")

        cancel = variant(
            QPushButton("Keluar" if startup else "Batal", clicked=self.reject), "ghost"
        )
        activate = variant(QPushButton("Aktivasi", clicked=self._activate), "primary")
        activate.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(activate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.current)
        layout.addWidget(QLabel("Key lisensi"))
        layout.addWidget(self.key_edit)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def _activate(self) -> None:
        text = self.key_edit.toPlainText().strip()
        if not text:
            self.status.setText("Tempel key lisensi terlebih dahulu.")
            return
        try:
            lic = validate_license(text)
            save_license(self._data_dir, lic)
        except LicenseError as exc:
            self.status.setText(str(exc))
            return
        except OSError as exc:
            self.status.setText(f"Lisensi valid, tetapi tidak bisa disimpan: {exc}")
            return
        self.license = lic
        self.accept()
