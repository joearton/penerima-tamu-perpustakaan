from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
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
from library_visitor.anonymous import AnonymousTracker
from library_visitor.audio import Announcer
from library_visitor.camera import FaceResult
from library_visitor.config import Settings
from library_visitor.extensions import DirectoryPerson, ExtensionError, MemberDirectory
from library_visitor.services import ServiceError, VisitorService, VisitResult
from library_visitor.ui.member_completer import MemberCompleter
from library_visitor.ui.theme import role, variant
from library_visitor.ui.today_visits import TodayVisitsCard
from library_visitor.ui.widgets import VideoView, logo_pixmap, resizable_split

log = logging.getLogger(__name__)

# Jeda sebelum anggota yang sama diproses lagi dari kamera (mencegah spam ke database)
RECHECK_SECONDS = 10

IDLE_STYLE = "background:#334155;"
OK_STYLE = "background:#16A34A;"
INFO_STYLE = "background:#2563EB;"
ERROR_STYLE = "background:#DC2626;"


class GuestDialog(QDialog):
    """Form tamu ringkas untuk mode kios."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tamu (non-anggota)")
        self.setMinimumWidth(460)
        self.setStyleSheet("font-size:18px;")
        self.name = QLineEdit()
        self.purpose = QLineEdit(placeholderText="mis. membaca, riset, kunjungan dinas")
        form = QFormLayout(self)
        form.addRow("Nama", self.name)
        form.addRow("Keperluan", self.purpose)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Catat Kunjungan")
        variant(ok, "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Batal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class VisitPage(QWidget):
    """Halaman pencatatan kunjungan. `kiosk=True` memakai tata letak besar untuk pengunjung."""

    members_changed = Signal()
    visit_recorded = Signal()
    kiosk_requested = Signal()
    _lookup_done = Signal(str, object)  # nomor, DirectoryPerson | None
    _lookup_failed = Signal(str)

    def __init__(
        self,
        service: VisitorService,
        settings: Settings,
        announcer: Announcer,
        directory: MemberDirectory | None = None,
        kiosk: bool = False,
        anonymous: AnonymousTracker | None = None,
    ) -> None:
        super().__init__()
        self._kiosk = kiosk
        self._anonymous = anonymous
        self._directory = directory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="visit-lookup")
        self._lookup_done.connect(self._on_lookup_done)
        self._lookup_failed.connect(self._on_lookup_failed)
        self._service = service
        self._settings = settings
        self._announcer = announcer
        self._streaks: dict[int, int] = {}  # member_id -> frame berturut-turut dikenali
        self._spoof_streak = 0
        self._last_handled: dict[int, float] = {}

        self.title = QLabel()
        self.title.setStyleSheet(f"font-size:{34 if kiosk else 24}px; font-weight:700;")
        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock.setStyleSheet(f"font-size:{26 if kiosk else 18}px; color:#64748B;")
        clock_timer = QTimer(self, interval=1000)
        clock_timer.timeout.connect(self._tick)
        clock_timer.start()
        # Identitas: logo, nama perpustakaan, lalu institusi (dari lisensi) · alamat · kontak
        self.logo = QLabel()
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet(f"font-size:{18 if kiosk else 13}px; color:#64748B;")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self.logo)
        header.addLayout(titles, 1)
        header.addWidget(self.clock)
        if not kiosk:
            kiosk_btn = QPushButton("Mode Kios  (F10)", clicked=lambda: self.kiosk_requested.emit())
            header.addWidget(kiosk_btn)

        self.video = VideoView()
        self.banner = QLabel()
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setWordWrap(True)
        self._banner_timer = QTimer(self, singleShot=True)
        self._banner_timer.timeout.connect(self._idle_banner)

        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.banner)

        self.member_no = QLineEdit()
        self.member_no.returnPressed.connect(self._record_manual)
        manual_btn = variant(QPushButton("Catat", clicked=self._record_manual), "primary")
        self.today = TodayVisitsCard()
        right = QVBoxLayout()

        if kiosk:
            self.member_no.setPlaceholderText("Scan kartu atau ketik NIM / NIDN, lalu Enter")
            self.member_no.setMinimumHeight(52)
            self.member_no.setStyleSheet("font-size:20px; padding:6px 10px;")
            manual_btn.setMinimumHeight(52)
            manual_btn.setStyleSheet("font-size:18px; font-weight:bold; padding:0 18px;")
            scan_row = QHBoxLayout()
            scan_row.addWidget(self.member_no, 1)
            scan_row.addWidget(manual_btn)
            guest_btn = QPushButton("Saya tamu (bukan anggota)", clicked=self._guest_dialog)
            guest_btn.setMinimumHeight(48)
            guest_btn.setStyleSheet("font-size:17px;")
            hint = role(QLabel("Esc: keluar dari mode kios (admin)"), "caption")
            hint.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(self.today, 1)
            right.addLayout(scan_row)
            right.addWidget(guest_btn)
            right.addWidget(hint)
        else:
            self.member_no.setPlaceholderText("No. anggota / NIM / nama, atau scan barcode")
            # Bukan di mode kios: daftar nama anggota lain tidak boleh tampil ke publik.
            # Memilih saran dengan Enter langsung mencatat (returnPressed menyusul).
            MemberCompleter(self.member_no, service, directory, "member_no")
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
            guest_form.addRow(
                variant(QPushButton("Catat Tamu", clicked=self._record_guest), "primary")
            )
            right.addWidget(manual_box)
            right.addWidget(guest_box)
            right.addWidget(self.today, 1)

        body = resizable_split(left, right, settings, "kiosk" if kiosk else "visit")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        if kiosk:
            layout.setContentsMargins(24, 16, 24, 16)
        else:
            layout.setContentsMargins(16, 14, 16, 14)
        layout.addLayout(header)
        layout.addWidget(body, 1)

        self.apply_settings()
        self._tick()
        self.refresh()

    def apply_settings(self) -> None:
        s = self._settings
        self.title.setText(s.library_name)
        details = [s.licensee, s.library_address, s.library_contact]
        self.subtitle.setText("  ·  ".join(x for x in details if x))
        self.subtitle.setVisible(any(details))
        self.logo.setPixmap(logo_pixmap(s, 72 if self._kiosk else 48))
        if self._kiosk:
            self.today.set_show_names(self._settings.kiosk_show_names)
            self.refresh()
        self._banner_timer.setInterval(self._settings.banner_seconds * 1000)
        if not self._banner_timer.isActive():
            self._idle_banner()

    # ---------- kamera ----------

    def on_frame(self, image: QImage, results: list[FaceResult]) -> None:
        self.video.show_image(image)
        # Hasil sudah urut dari wajah terbesar (terdekat). Mode satu wajah: hanya yang terdekat.
        faces = results if self._settings.multi_face else results[:1]

        if any(r.spoof for r in faces):
            self._spoof_streak += 1
            if self._spoof_streak == self._settings.stable_frames:
                score = min(r.real_score for r in faces if r.spoof)
                log.warning("Wajah palsu terdeteksi (skor asli %.2f)", score)
                self._show(
                    "Wajah tidak terdeteksi asli. Hadapkan wajah langsung ke kamera.",
                    ERROR_STYLE,
                )
        else:
            self._spoof_streak = 0

        # Konfirmasi per orang: anggota harus dikenali di N frame berturut-turut
        seen = {r.match.member_id: r.match for r in faces if r.match and not r.spoof}
        self._streaks = {mid: self._streaks.get(mid, 0) + 1 for mid in seen}
        now = time.monotonic()
        ready = [
            seen[mid]
            for mid, count in self._streaks.items()
            if count >= self._settings.stable_frames
            and now - self._last_handled.get(mid, 0) >= RECHECK_SECONDS
        ]
        visit_results = []
        for match in ready:
            self._last_handled[match.member_id] = now
            self._streaks[match.member_id] = 0
            try:
                visit_results.append(
                    self._service.record_member_visit(match.member_id, "face", match.score)
                )
            except ServiceError as exc:
                self._show(str(exc), ERROR_STYLE)
        if visit_results:
            self._greet_many(visit_results)

        if self._anonymous is not None and self._settings.anonymous_enabled:
            unknown = [
                r.embedding
                for r in faces
                if r.embedding is not None and r.match is None and not r.spoof
            ]
            self._record_anonymous(unknown, now, greeted=bool(visit_results))

    def _record_anonymous(self, unknown: list, now: float, greeted: bool) -> None:
        recorded = 0
        for embedding in self._anonymous.observe(unknown, now):
            try:
                visit = self._service.record_anonymous_visit()
            except ServiceError as exc:
                self._show(str(exc), ERROR_STYLE)
                continue
            self._anonymous.attach(embedding, visit.id, now)
            recorded += 1
        if not recorded:
            return
        log.info("Kunjungan anonim: %d orang", recorded)
        if not greeted:  # sapaan anggota (bila ada di frame yang sama) didahulukan
            s = self._settings
            text = greeting.render_group(s.anonymous_template, [], s.library_name)
            self._show(text, OK_STYLE)
            self._announcer.announce(text)
        self.refresh()
        self.visit_recorded.emit()

    def _claim_anonymous(self) -> None:
        """Orang di depan kamera ternyata scan kartu/isi form tamu: jangan dihitung anonim."""
        if self._anonymous is None:
            return
        visit_id = self._anonymous.claim_recent(time.monotonic())
        if visit_id is not None:
            self._service.delete_visit(visit_id)
            log.info("Kunjungan anonim #%d digabung dengan pencatatan manual", visit_id)

    # ---------- input manual ----------

    def _record_manual(self) -> None:
        number = self.member_no.text().strip()
        if not number:
            return
        if self._service.get_member_by_no(number) is None and self._directory is not None:
            # Belum terdaftar lokal: ambil dari direktori, daftarkan tanpa wajah, lalu catat
            self.member_no.setEnabled(False)
            self._show(f"Mencari {number} di direktori...", INFO_STYLE)
            self._executor.submit(self._lookup_worker, number)
            return
        try:
            result = self._service.record_manual_visit(number)
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return
        self.member_no.clear()
        self._claim_anonymous()
        self._greet(result)

    def _lookup_worker(self, number: str) -> None:
        try:
            self._lookup_done.emit(number, self._directory.lookup(number))
        except ExtensionError as exc:
            self._lookup_failed.emit(str(exc))

    def _on_lookup_done(self, number: str, person: DirectoryPerson | None) -> None:
        self.member_no.setEnabled(True)
        self.member_no.setFocus()
        if person is None:
            self._show(f"No. {number} tidak ditemukan. Silakan isi sebagai tamu.", ERROR_STYLE)
            return
        try:
            member = self._service.save_member(
                number,
                person.name,
                person.category,
                unit=person.unit,
                directory_status=person.status,
            )
            result = self._service.record_member_visit(member.id, "manual")
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return
        log.info("Anggota baru dari direktori saat kunjungan: %s", number)
        self.member_no.clear()
        self.members_changed.emit()
        self._claim_anonymous()
        self._greet(result)

    def _on_lookup_failed(self, message: str) -> None:
        self.member_no.setEnabled(True)
        self.member_no.setFocus()
        self._show(message, ERROR_STYLE)

    def _record_guest(self) -> None:
        if self.record_guest(self.guest_name.text(), self.guest_purpose.text()):
            self.guest_name.clear()
            self.guest_purpose.clear()

    def _guest_dialog(self) -> None:
        dialog = GuestDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.record_guest(dialog.name.text(), dialog.purpose.text())
        self.member_no.setFocus()

    def record_guest(self, name: str, purpose: str) -> bool:
        name = name.strip()
        try:
            self._service.record_guest_visit(name, purpose)
        except ServiceError as exc:
            self._show(str(exc), ERROR_STYLE)
            return False
        self._claim_anonymous()
        s = self._settings
        text = greeting.render(s.guest_template, name, "Tamu", s.library_name)
        self._show(text, OK_STYLE)
        self._announcer.announce(text)
        self.refresh()
        self.visit_recorded.emit()
        return True

    # ---------- tampilan ----------

    def _greet(self, result: VisitResult) -> None:
        self._greet_many([result])

    def _greet_many(self, results: list[VisitResult]) -> None:
        """Satu sapaan (dan satu ucapan suara) untuk semua yang tercatat bersamaan."""
        s = self._settings
        new = [r.member for r in results if r.visit is not None]
        repeat = [r.member for r in results if r.visit is None]
        if not new:
            people = [(m.name, m.category) for m in repeat]
            text = greeting.render_group(s.repeat_template, people, s.library_name)
            self._show(text, INFO_STYLE)
            if s.speak_repeat:
                self._announcer.announce(text, chime=False)
            return
        for r in results:
            if r.visit is not None:
                m = r.member
                log.info("Kunjungan: %s (%s) via %s", m.name, m.member_no, r.visit.method)
        people = [(m.name, m.category) for m in new]
        text = greeting.render_group(s.greeting_template, people, s.library_name)
        self._show(text, OK_STYLE)
        self._announcer.announce(text)
        self.refresh()
        self.visit_recorded.emit()

    def _show(self, text: str, style: str) -> None:
        self.banner.setText(text)
        self.banner.setStyleSheet(
            f"font-size:{32 if self._kiosk else 24}px; font-weight:bold; color:white;"
            f" padding:{22 if self._kiosk else 14}px; border-radius:12px;" + style
        )
        if style != IDLE_STYLE:
            self._banner_timer.start()

    def _idle_banner(self) -> None:
        if self._kiosk:
            self._show("Silakan menghadap kamera atau scan kartu anggota", IDLE_STYLE)
        else:
            self._show("Silakan menghadap kamera", IDLE_STYLE)

    def _tick(self) -> None:
        self.clock.setText(datetime.now().strftime("%d-%m-%Y  %H:%M:%S"))

    def refresh(self) -> None:
        today = date.today()
        self.today.set_visits(self._service.visits_between(today, today))

    def on_camera_error(self, message: str) -> None:
        self.video.show_message(message)
