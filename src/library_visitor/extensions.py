"""Integrasi opsional dengan sistem institusi: direktori anggota dan login admin eksternal.

Keduanya aktif hanya bila variabel lingkungannya diisi di .env; tanpa itu aplikasi berjalan
penuh secara lokal. Implementasi lain cukup memenuhi Protocol di bawah.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


class ExtensionError(Exception):
    """Galat yang pesannya aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class DirectoryPerson:
    member_no: str
    name: str
    category: str  # salah satu services.CATEGORIES
    unit: str
    status: str


class MemberDirectory(Protocol):
    label: str  # teks tombol, mis. "Cari di direktori"

    def lookup(self, number: str) -> DirectoryPerson | None: ...


@dataclass(frozen=True)
class AdminUser:
    username: str
    name: str
    groups: tuple[str, ...] = ()


class AdminLoginSession(Protocol):
    def run(self, open_browser: Callable[[str], object]) -> AdminUser: ...

    def cancel(self) -> None: ...


class AdminLoginProvider(Protocol):
    label: str  # teks tombol, mis. "Masuk dengan akun kampus"

    def start(self) -> AdminLoginSession: ...


@dataclass(frozen=True)
class Extensions:
    directory: MemberDirectory | None = None
    admin_login: AdminLoginProvider | None = None


def load_extensions() -> Extensions:
    """Aktifkan integrasi yang variabel lingkungannya sudah diisi (lihat .env.example)."""
    from library_visitor.directory_api import ApiDirectory
    from library_visitor.oidc_login import OAuthLoginProvider

    try:
        extensions = Extensions(ApiDirectory.from_env(), OAuthLoginProvider.from_env())
    except ValueError as exc:
        log.error("Konfigurasi integrasi tidak valid: %s", exc)
        return Extensions()
    log.info(
        "Integrasi: direktori anggota %s, login admin eksternal %s",
        "aktif" if extensions.directory else "nonaktif",
        "aktif" if extensions.admin_login else "nonaktif",
    )
    return extensions


def parse_admin_usernames(text: str) -> set[str]:
    return {u.strip().lower() for u in text.replace(",", " ").split() if u.strip()}


def is_admin(user: AdminUser, usernames: set[str], group: str) -> bool:
    if user.username.lower() in usernames:
        return True
    return bool(group) and group.lower() in {g.lower() for g in user.groups}
