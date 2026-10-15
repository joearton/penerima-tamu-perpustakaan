from __future__ import annotations

import logging
import time
from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library_visitor import greeting
from library_visitor.audio import Announcer
from library_visitor.camera import FaceResult
from library_visitor.config import Settings
from library_visitor.reports import METHOD_LABELS
from library_visitor.services import ServiceError, VisitorService, VisitResult, visitor_name
from library_visitor.ui.widgets import VideoView, fill_table, make_table

log = logging.getLogger(__name__)

# Jeda sebelum anggota yang sama diproses lagi dari kamera (mencegah spam ke database)
RECHECK_SECONDS = 10

IDLE_STYLE = "background:#34495e;"
OK_STYLE = "background:#1e8449;"
INFO_STYLE = "background:#2471a3;"
ERROR_STYLE = "background:#c0392b;"


class VisitPage(QWidget):
    def __init__(self, service: VisitorService, settings: Settings, announcer: Announcer) -> None:
        super().__init__()
        self._service = service
        self._settings = settings
        self._announcer = announcer
        self._candidate: int | None = None
        self._streak = 0
        self._last_handled: dict[int, float] = {}

        self.title = QLabel()
        self.title.setStyleSheet("font-size:24px; font-weight:bold;")
        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock.setStyleSheet("font-size:18px; color:#555;")
        clock_timer = QTimer(self, interval=1000)
        clock_timer.timeout.connect(self._tick)
        clock_timer.start()
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        header.addWidget(self.clock)

        self.video = VideoView()
        self.banner = QLabel()
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setWordWrap(True)
        self._banner_timer = QTimer(self, singleShot=True)
        self._banner_timer.timeout.connect(self._idle_banner)

        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.banner)

        self.today_label = QLabel()
        self.today_label.setStyleSheet("font-size:16px; font-weight:bold;")

        self.member_no = QLineEdit(placeholderText="No. anggota / NIM / scan barcode")
        self.member_no.returnPressed.connect(self._record_manual)
        manual_btn = QPushButton("Catat", clicked=self._record_manual)
        manual_box = QGroupBox("Input manual")
        manual_row = QHBoxLayout(manual_box)
        manual_row.addWidget(self.member_no, 1)
        manual_row.addWidget(manual_btn)

        self.guest_name = QLineEdit()
        self.guest_purpose = QLineEdit()
        guest_box = QGroupBox("Tamu (non-anggota)")
        guest_form = QFormLayout(guest_box)
        guest_form.addRow("Nama", self.guest_name)
        guest_form.addRow("Keperluan", self.guest_purpose)
        guest_form.addRow(QPushButton("Catat Tamu", clicked=self._record_guest))

        self.table = make_table(["Jam", "Nama", "Metode"])

        right = QVBoxLayout()
        right.addWidget(self.today_label)
        right.addWidget(manual_box)
        right.addWidget(guest_box)
        right.addWidget(QLabel("Kunjungan hari ini"))
        right.addWidget(self.table, 1)

        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addLayout(body, 1)

        self.apply_settings()
        self._tick()
        self.refresh()

    def apply_settings(self) -> None:
        self.title.setText(self._settings.library_name)
        self._banner_timer.setInterval(self._settings.banner_seconds * 1000)
        if not self._banner_timer.isActive():
            self._idle_banner()

    # ---------- kamera ----------

    def on_frame(self, image: QImage, results: list[FaceResult]) -> None:
        self.video.show_image(image)
        match = results[0].match if results else None  # hanya wajah terbesar (terdekat)
        if match is None:
            self._candidate, self._streak = None, 0
            return
        if match.member_id == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = match.member_id, 1
        if self._streak < self._settings.stable_frames:
            return

        now = time.monotonic()
        if now - self._last_handled.get(match.member_id, 0) < RECHECK_SECONDS:
            return
        self._last_handled[match.member_id] = now
        self._streak = 0
        try:
            result = self._service.record_member_visit(match.member_id, "face", match.score)
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return
        self._greet(result)

    # ---------- input manual ----------

    def _record_manual(self) -> None:
        if not self.member_no.text().strip():
            return
        try:
            result = self._service.record_manual_visit(self.member_no.text())
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return
        self.member_no.clear()
        self._greet(result)

    def _record_guest(self) -> None:
        name = self.guest_name.text().strip()
        try:
            self._service.record_guest_visit(name, self.guest_purpose.text())
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return
        s = self._settings
        text = greeting.render(s.guest_template, name, "Tamu", s.library_name)
        self._show(text, OK_STYLE)
        self._announcer.announce(text)
        self.guest_name.clear()
        self.guest_purpose.clear()
        self.refresh()

    # ---------- tampilan ----------

    def _greet(self, result: VisitResult) -> None:
        s = self._settings
        member = result.member
        if result.visit is None:
            text = greeting.render(s.repeat_template, member.name, member.category, s.library_name)
            self._show(text, INFO_STYLE)
            if s.speak_repeat:
                self._announcer.announce(text, chime=False)
            return
        log.info("Kunjungan: %s (%s) via %s", member.name, member.member_no, result.visit.method)
        text = greeting.render(s.greeting_template, member.name, member.category, s.library_name)
        self._show(text, OK_STYLE)
        self._announcer.announce(text)
        self.refresh()

    def _show(self, text: str, style: str) -> None:
        self.banner.setText(text)
        self.banner.setStyleSheet(
            "font-size:24px; font-weight:bold; color:white; padding:14px; border-radius:6px;"
            + style
        )
        if style != IDLE_STYLE:
            self._banner_timer.start()

    def _idle_banner(self) -> None:
        self._show("Silakan menghadap kamera", IDLE_STYLE)

    def _tick(self) -> None:
        self.clock.setText(datetime.now().strftime("%d-%m-%Y  %H:%M:%S"))

    def refresh(self) -> None:
        today = date.today()
        visits = self._service.visits_between(today, today)
        self.today_label.setText(f"Pengunjung hari ini: {len(visits)}")
        fill_table(
            self.table,
            [
                [v.visited_at.strftime("%H:%M"), visitor_name(v), METHOD_LABELS.get(v.method)]
                for v in visits
            ],
        )

    def on_camera_error(self, message: str) -> None:
        self.video.show_message(message)
