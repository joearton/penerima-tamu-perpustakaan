from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library_visitor.db import Member
from library_visitor.services import VisitorService
from library_visitor.ui.theme import variant
from library_visitor.ui.widgets import fill_table, make_table


class MembersPage(QWidget):
    members_changed = Signal()

    def __init__(self, service: VisitorService) -> None:
        super().__init__()
        self._service = service
        self._members: list[Member] = []

        self.search = QLineEdit(placeholderText="Cari nama / no. anggota...")
        self.search.textChanged.connect(self.refresh)
        self.table = make_table(
            [
                "No. Anggota",
                "Nama",
                "Kategori",
                "Prodi/Unit",
                "Status Direktori",
                "Wajah",
                "Terdaftar",
            ]
        )

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(QPushButton("Hapus Data Wajah", clicked=self._delete_face))
        toolbar.addWidget(
            variant(QPushButton("Hapus Anggota", clicked=self._delete_member), "danger")
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self._members = self._service.list_members(self.search.text())
        fill_table(
            self.table,
            [
                [
                    m.member_no,
                    m.name,
                    m.category,
                    m.unit,
                    m.directory_status or "-",
                    "Ya" if m.face_embedding else "Tidak",
                    m.created_at.strftime("%d-%m-%Y"),
                ]
                for m in self._members
            ],
        )

    def _selected(self) -> Member | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._members):
            return self._members[row]
        QMessageBox.information(self, "Pilih anggota", "Pilih satu anggota di tabel dulu.")
        return None

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def _delete_face(self) -> None:
        member = self._selected()
        if member and self._confirm("Hapus data wajah", f"Hapus data wajah {member.name}?"):
            self._service.delete_face(member.id)
            self._changed()

    def _delete_member(self) -> None:
        member = self._selected()
        if member and self._confirm(
            "Hapus anggota",
            f"Hapus {member.name}? Riwayat kunjungannya tetap ada tetapi dianonimkan.",
        ):
            self._service.delete_member(member.id)
            self._changed()

    def _changed(self) -> None:
        self.refresh()
        self.members_changed.emit()
