from __future__ import annotations

import logging
import threading
import webbrowser

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from library_visitor.config import Settings
from library_visitor.extensions import (
    AdminLoginProvider,
    AdminLoginSession,
    AdminUser,
    ExtensionError,
    is_admin,
    parse_admin_usernames,
)
from library_visitor.ui.theme import variant

log = logging.getLogger(__name__)


def external_admin_enabled(settings: Settings, provider: AdminLoginProvider | None) -> bool:
    return provider is not None and bool(
        parse_admin_usernames(settings.admin_usernames) or settings.admin_group.strip()
    )


class AdminAuthDialog(QDialog):
    """Membuka tab admin dengan PIN lokal dan/atau login lewat ekstensi."""

    _login_ok = Signal(object)
    _login_failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        provider: AdminLoginProvider | None,
        parent=None,
        allow_quit: bool = False,
    ) -> None:
        """`allow_quit`: tampilkan tombol "Tutup Aplikasi" (tanpa PIN) agar admin yang lupa PIN
        tidak terkunci di Mode Kios. Menutup aplikasi tidak membuka akses data/pengaturan."""
        super().__init__(parent)
        self.quit_requested = False
        self.setWindowTitle("Akses Admin")
        self.setMinimumWidth(380)
        self._settings = settings
        self._provider = provider
        self._session: AdminLoginSession | None = None
        self.admin_name = ""
        self._login_ok.connect(self._on_login_ok)
        self._login_failed.connect(self._on_login_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        self.status = QLabel()
        self.status.setWordWrap(True)

        if settings.pin_enabled:
            self.pin = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
            self.pin.returnPressed.connect(self._check_pin)
            form = QFormLayout()
            form.addRow("PIN admin", self.pin)
            layout.addLayout(form)
            layout.addWidget(
                variant(QPushButton("Masuk dengan PIN", clicked=self._check_pin), "primary")
            )

        if external_admin_enabled(settings, provider):
            self.login_btn = QPushButton(provider.label, clicked=self._start_login)
            layout.addWidget(self.login_btn)

        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        if allow_quit:
            quit_btn = variant(QPushButton("Tutup Aplikasi"), "danger")
            quit_btn.setAutoDefault(False)  # Enter di kolom PIN tidak boleh menutup aplikasi
            quit_btn.clicked.connect(self._quit)
            buttons.addButton(quit_btn, QDialogButtonBox.ButtonRole.DestructiveRole)
            hint = QLabel("Lupa PIN? Tutup aplikasi, lalu reset PIN: library-visitor --reset-pin")
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#64748B; font-size:11px;")
            layout.addWidget(hint)
        layout.addWidget(buttons)

    def _check_pin(self) -> None:
        if self._settings.check_pin(self.pin.text()):
            self.admin_name = "PIN lokal"
            self.accept()
        else:
            log.warning("PIN admin salah di aplikasi (panjang input %d)", len(self.pin.text()))
            self.pin.clear()
            self.status.setText("PIN salah.")

    def _quit(self) -> None:
        log.info("Aplikasi ditutup dari dialog PIN (tanpa PIN)")
        self.quit_requested = True
        self.reject()

    def _start_login(self) -> None:
        try:
            self._session = self._provider.start()
        except ExtensionError as exc:
            self.status.setText(str(exc))
            return
        self.login_btn.setEnabled(False)
        self.status.setText("Silakan login di browser yang terbuka...")
        session = self._session
        threading.Thread(target=self._login_worker, args=(session,), daemon=True).start()

    def _login_worker(self, session: AdminLoginSession) -> None:
        try:
            self._login_ok.emit(session.run(webbrowser.open))
        except ExtensionError as exc:
            self._login_failed.emit(str(exc))

    def _on_login_ok(self, user: AdminUser) -> None:
        s = self._settings
        if is_admin(user, parse_admin_usernames(s.admin_usernames), s.admin_group.strip()):
            log.info("Admin masuk via ekstensi: %s", user.username)
            self.admin_name = user.name or user.username
            self.accept()
            return
        log.warning("Login ditolak, bukan admin: %s", user.username)
        self.login_btn.setEnabled(True)
        self.status.setText(f"Akun {user.username} tidak terdaftar sebagai admin.")

    def _on_login_failed(self, message: str) -> None:
        if self.isVisible():
            self.login_btn.setEnabled(True)
            self.status.setText(message)

    def done(self, result: int) -> None:
        if self._session is not None:
            self._session.cancel()
        super().done(result)
