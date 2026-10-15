from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library_visitor.reports import REPORT_COLUMNS, export_excel, visits_dataframe
from library_visitor.services import VisitorService
from library_visitor.ui.widgets import fill_table, make_table


def _date_edit(value: QDate) -> QDateEdit:
    edit = QDateEdit(value, calendarPopup=True)
    edit.setDisplayFormat("dd-MM-yyyy")
    return edit


class ReportPage(QWidget):
    def __init__(self, service: VisitorService) -> None:
        super().__init__()
        self._service = service
        today = QDate.currentDate()
        self.start = _date_edit(QDate(today.year(), today.month(), 1))
        self.end = _date_edit(today)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight:bold;")
        self.table = make_table(list(REPORT_COLUMNS))

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Dari"))
        toolbar.addWidget(self.start)
        toolbar.addWidget(QLabel("s/d"))
        toolbar.addWidget(self.end)
        toolbar.addWidget(QPushButton("Tampilkan", clicked=self.refresh))
        toolbar.addStretch(1)
        toolbar.addWidget(QPushButton("Ekspor Excel", clicked=self._export))

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.summary)
        layout.addWidget(self.table)

    def _range(self):
        return self.start.date().toPython(), self.end.date().toPython()

    def refresh(self) -> None:
        df = visits_dataframe(self._service, *self._range())
        per_category = Counter(df["Kategori"])
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(per_category.items()))
        self.summary.setText(f"Total kunjungan: {len(df)}" + (f"  ({detail})" if detail else ""))
        df["Waktu"] = df["Waktu"].map(lambda t: t.strftime("%d-%m-%Y %H:%M"))
        fill_table(self.table, df.values.tolist())

    def _export(self) -> None:
        start, end = self._range()
        default = f"kunjungan_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Simpan laporan", default, "Excel (*.xlsx)")
        if not path:
            return
        count = export_excel(self._service, start, end, Path(path))
        QMessageBox.information(self, "Ekspor selesai", f"{count} kunjungan diekspor ke\n{path}")
