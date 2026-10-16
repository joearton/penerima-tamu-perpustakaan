"""Kartu "Kunjungan Hari Ini" di halaman Kunjungan."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from library_visitor.db import Visit
from library_visitor.reports import METHOD_LABELS
from library_visitor.services import visit_category, visitor_name

METHOD_COLORS = {
    "face": "#1e8449",
    "manual": "#2471a3",
    "guest": "#b9770e",
    "anonymous": "#7f8c8d",
}
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
COL_TIME, COL_NAME, COL_CATEGORY, COL_METHOD = range(4)


class _NameDelegate(QStyledItemDelegate):
    """Nama (tebal) dengan prodi/unit (abu-abu, lebih kecil) di bawahnya."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name, subtitle = opt.text, index.data(SUBTITLE_ROLE) or ""
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        rect = opt.rect.adjusted(8, 4, -8, -4)
        name_font = QFont(opt.font)
        name_font.setBold(True)
        sub_font = QFont(opt.font)
        sub_font.setPointSizeF(opt.font.pointSizeF() * 0.85)
        name_h = QFontMetrics(name_font).height()
        sub_h = QFontMetrics(sub_font).height() if subtitle else 0
        top = rect.top() + (rect.height() - name_h - sub_h) // 2

        painter.save()
        painter.setFont(name_font)
        painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        name_rect = QRect(rect.left(), top, rect.width(), name_h)
        elided = QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(
            name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided
        )
        if subtitle:
            painter.setFont(sub_font)
            painter.setPen(opt.palette.color(QPalette.ColorRole.PlaceholderText))
            sub_rect = QRect(rect.left(), top + name_h, rect.width(), sub_h)
            sub = QFontMetrics(sub_font).elidedText(
                subtitle, Qt.TextElideMode.ElideRight, rect.width()
            )
            painter.drawText(
                sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub
            )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 46))


def _item(text: str, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return item


class TodayVisitsCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("todayCard")
        self.setStyleSheet(
            "#todayCard { background: palette(base); border: 1px solid palette(mid);"
            " border-radius: 8px; }"
        )

        title = QLabel("Kunjungan Hari Ini")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        self.count = QLabel("0")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setMinimumWidth(36)
        self.count.setStyleSheet(
            "background:#1e8449; color:white; font-weight:bold; font-size:14px;"
            " border-radius:11px; padding:2px 10px;"
        )
        self.summary = QLabel()
        self.summary.setStyleSheet("color: palette(placeholder-text);")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addWidget(self.count)
        header.addStretch(1)
        header.addWidget(self.summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Jam", "Nama", "Kategori", "Metode"])
        self.table.setItemDelegateForColumn(COL_NAME, _NameDelegate(self.table))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        head.setHighlightSections(False)
        for col in (COL_TIME, COL_CATEGORY, COL_METHOD):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(
            "QTableWidget { background: transparent; }"
            "QHeaderView::section { background: transparent; border: none;"
            " border-bottom: 1px solid palette(mid); padding: 6px 8px; font-weight: bold; }"
            "QTableWidget::item { padding: 0 8px; }"
        )

        # Tampilan privasi (layar kios): hanya angka, tanpa nama pengunjung
        self._show_names = True
        self.big_count = QLabel("0")
        self.big_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_count.setStyleSheet("font-size:96px; font-weight:bold; color:#1e8449;")
        self.big_caption = QLabel("pengunjung hari ini")
        self.big_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_caption.setStyleSheet("font-size:20px; color: palette(placeholder-text);")
        self.big_detail = QLabel()
        self.big_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_detail.setStyleSheet("font-size:16px;")
        stats = QWidget()
        stats_layout = QVBoxLayout(stats)
        stats_layout.addStretch(1)
        stats_layout.addWidget(self.big_count)
        stats_layout.addWidget(self.big_caption)
        stats_layout.addSpacing(12)
        stats_layout.addWidget(self.big_detail)
        stats_layout.addStretch(1)
        self.stats = stats

        self.empty = QLabel("Belum ada kunjungan hari ini")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: palette(placeholder-text); font-size:14px;")
        self._stack = QStackedLayout()
        self._stack.addWidget(self.empty)
        self._stack.addWidget(self.table)
        self._stack.addWidget(self.stats)
        stack_holder = QWidget()
        stack_holder.setLayout(self._stack)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addLayout(header)
        layout.addWidget(stack_holder, 1)

    def set_show_names(self, show: bool) -> None:
        self._show_names = show

    def set_visits(self, visits: list[Visit]) -> None:
        guests = sum(1 for v in visits if v.method == "guest")
        anonymous = sum(1 for v in visits if v.method == "anonymous")
        members = len(visits) - guests - anonymous
        self.count.setText(str(len(visits)))
        parts = [f"{members} anggota", f"{guests} tamu"] + (
            [f"{anonymous} anonim"] if anonymous else []
        )
        self.summary.setText(" · ".join(parts) if visits else "")
        if not self._show_names:
            per_category = Counter(visit_category(v) for v in visits)
            self.big_count.setText(str(len(visits)))
            self.big_detail.setText(
                "   ·   ".join(f"{k}: {n}" for k, n in sorted(per_category.items()))
            )
            self._stack.setCurrentWidget(self.stats)
            self.table.setRowCount(0)  # jangan simpan nama di widget yang tersembunyi
            return
        self._stack.setCurrentWidget(self.table if visits else self.empty)

        self.table.setRowCount(len(visits))
        for row, v in enumerate(visits):  # sudah urut terbaru dulu
            time_item = _item(v.visited_at.strftime("%H:%M"), Qt.AlignmentFlag.AlignCenter)
            time_item.setForeground(QColor("#7f8c8d"))
            name_item = _item(visitor_name(v))
            if v.member is not None:
                name_item.setData(SUBTITLE_ROLE, v.member.unit or v.member.member_no)
            elif v.purpose:
                name_item.setData(SUBTITLE_ROLE, f"Keperluan: {v.purpose}")
            category = visit_category(v)
            method_item = _item(METHOD_LABELS.get(v.method, v.method))
            method_item.setForeground(QColor(METHOD_COLORS.get(v.method, "#555")))
            bold = method_item.font()
            bold.setBold(True)
            method_item.setFont(bold)
            for col, item in (
                (COL_TIME, time_item),
                (COL_NAME, name_item),
                (COL_CATEGORY, _item(category)),
                (COL_METHOD, method_item),
            ):
                self.table.setItem(row, col, item)
