from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLayout,
    QMenu,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from library_visitor.config import Settings

SPLITTER_SAVE_DELAY_MS = 800


class VideoView(QLabel):
    """Menampilkan frame kamera dengan rasio aspek tetap.

    `camera_switch=True` menambah tombol "Ganti Kamera" di pojok kanan atas (bukan untuk kios).
    """

    camera_selected = Signal(int)  # indeks kamera yang dipilih

    def __init__(self, camera_switch: bool = False) -> None:
        super().__init__("Kamera belum aktif")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#0F172A; color:#94A3B8; border-radius:12px; font-size:14px;")
        self.current_camera = 0
        self.switch_button: QToolButton | None = None
        if camera_switch:
            button = QToolButton(self)
            button.setObjectName("cameraSwitch")
            button.setText("Ganti Kamera  ▾")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # fokus tetap di input scan kartu
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            menu.aboutToShow.connect(lambda: self._fill_camera_menu(menu))
            button.setMenu(menu)
            self.switch_button = button

    def _fill_camera_menu(self, menu: QMenu) -> None:
        """Daftar kamera dibaca saat menu dibuka, jadi webcam yang baru dicolok ikut muncul."""
        menu.clear()
        devices = QMediaDevices.videoInputs()
        if not devices:
            menu.addAction("Tidak ada kamera terdeteksi").setEnabled(False)
            return
        for i, device in enumerate(devices):
            action = menu.addAction(f"{device.description()}")
            action.setCheckable(True)
            action.setChecked(i == self.current_camera)
            action.triggered.connect(lambda _=False, i=i: self.camera_selected.emit(i))

    def set_current_camera(self, index: int) -> None:
        self.current_camera = index
        if self.switch_button is not None:
            devices = QMediaDevices.videoInputs()
            name = devices[index].description() if 0 <= index < len(devices) else f"#{index}"
            self.switch_button.setToolTip(f"Kamera aktif: {name}")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.switch_button is not None:
            self.switch_button.adjustSize()
            self.switch_button.move(self.width() - self.switch_button.width() - 12, 12)

    def show_image(self, image: QImage) -> None:
        self.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def show_message(self, text: str) -> None:
        self.clear()
        self.setText(text)


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(38)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setAlternatingRowColors(True)
    return table


def fill_table(table: QTableWidget, rows: list[list[object]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
    table.resizeColumnsToContents()
    for c in range(table.columnCount() - 1):  # sedikit ruang napas antar kolom
        table.setColumnWidth(c, table.columnWidth(c) + 24)


def resizable_split(
    left: QLayout, right: QLayout, settings: Settings, key: str, stretch=(3, 2)
) -> QSplitter:
    """Panel kiri/kanan dengan pembatas yang bisa digeser; posisinya diingat di settings.json."""
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(8)
    for index, layout in enumerate((left, right)):
        pane = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        pane.setLayout(layout)
        splitter.addWidget(pane)
        splitter.setStretchFactor(index, stretch[index])
    saved = settings.splitter_sizes.get(key)
    if isinstance(saved, list) and len(saved) == 2 and all(isinstance(x, int) for x in saved):
        splitter.setSizes(saved)

    save_timer = QTimer(splitter, singleShot=True, interval=SPLITTER_SAVE_DELAY_MS)

    def save() -> None:
        settings.splitter_sizes = {**settings.splitter_sizes, key: splitter.sizes()}
        settings.save()

    save_timer.timeout.connect(save)
    splitter.splitterMoved.connect(lambda *_: save_timer.start())  # simpan setelah selesai geser
    return splitter


def logo_pixmap(settings: Settings, size: int) -> QPixmap:
    """Logo lokasi (bila diatur) atau ikon aplikasi, diskalakan ke kotak `size`."""
    path = settings.logo_path
    pixmap = QPixmap(str(path)) if path else QPixmap()
    if pixmap.isNull():
        pixmap = QApplication.windowIcon().pixmap(size, size)
    return pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
