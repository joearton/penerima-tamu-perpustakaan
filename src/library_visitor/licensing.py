"""Lisensi aplikasi: key bertanda tangan Ed25519, diverifikasi offline.

Format key:  PTP1.<payload base64url>.<tanda tangan base64url>
Payload JSON: {"v": 1, "id", "licensee", "issued", "expires" (YYYY-MM-DD atau null)}

Aplikasi hanya memuat KUNCI PUBLIK di bawah; key dibuat dengan aplikasi license-generator
(folder terpisah, menyimpan kunci privat). Key tersimpan di data/license.key.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

log = logging.getLogger(__name__)

PREFIX = "PTP1"
PUBLIC_KEY = "N2liOv6aunO3cU8BgNCPWYkSk+M92z8vL147sJIjkyc="
LICENSE_FILE = "license.key"
EXPIRY_WARNING_DAYS = 30


class LicenseError(Exception):
    """Key tidak valid; pesannya aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class License:
    id: str
    licensee: str  # nama institusi pemegang lisensi
    issued: date
    expires: date | None  # None = tanpa batas waktu
    key: str

    def is_expired(self, today: date | None = None) -> bool:
        return self.expires is not None and (today or date.today()) > self.expires

    def days_left(self, today: date | None = None) -> int | None:
        if self.expires is None:
            return None
        return (self.expires - (today or date.today())).days

    def describe(self, today: date | None = None) -> str:
        if self.expires is None:
            validity = "berlaku tanpa batas waktu"
        elif self.is_expired(today):
            validity = f"kedaluwarsa sejak {self.expires:%d-%m-%Y}"
        else:
            validity = f"berlaku s/d {self.expires:%d-%m-%Y}"
        return f"{self.licensee} · {validity} · ID {self.id}"


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_license(key: str, public_key: str | None = None) -> License:
    """Verifikasi tanda tangan dan isi key. Tidak memeriksa masa berlaku."""
    public_key = public_key or PUBLIC_KEY
    key = "".join(key.split())  # toleran terhadap spasi/baris baru saat menempel
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("Format key lisensi tidak dikenali")
    try:
        payload_raw, signature = _unb64(parts[1]), _unb64(parts[2])
        verifier = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key))
        verifier.verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (binascii.Error, ValueError, InvalidSignature):
        raise LicenseError("Key lisensi tidak valid (tanda tangan tidak cocok)") from None
    try:
        payload = json.loads(payload_raw)
        if payload.get("v") != 1:
            raise LicenseError("Versi key lisensi tidak didukung; perbarui aplikasi")
        licensee = str(payload["licensee"]).strip()
        issued = date.fromisoformat(payload["issued"])
        expires = date.fromisoformat(payload["expires"]) if payload.get("expires") else None
        license_id = str(payload["id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LicenseError("Isi key lisensi rusak") from None
    if not licensee:
        raise LicenseError("Isi key lisensi rusak")
    return License(license_id, licensee, issued, expires, key)


def validate_license(key: str, today: date | None = None) -> License:
    """Seperti parse_license, ditambah menolak lisensi yang sudah kedaluwarsa."""
    lic = parse_license(key)
    if lic.is_expired(today):
        raise LicenseError(
            f"Lisensi untuk {lic.licensee} kedaluwarsa sejak {lic.expires:%d-%m-%Y}. "
            "Hubungi penyedia aplikasi untuk perpanjangan."
        )
    return lic


def license_path(data_dir: Path) -> Path:
    return data_dir / LICENSE_FILE


def check_stored_license(data_dir: Path) -> tuple[License | None, str]:
    """(lisensi valid, "") atau (None, alasan yang bisa ditampilkan; kosong bila belum ada)."""
    path = license_path(data_dir)
    if not path.exists():
        return None, ""
    try:
        return validate_license(path.read_text(encoding="utf-8")), ""
    except OSError as exc:
        log.warning("Lisensi tersimpan tidak bisa dibaca: %s", exc)
        return None, f"File lisensi tidak bisa dibaca: {exc}"
    except LicenseError as exc:
        log.warning("Lisensi tersimpan tidak dipakai: %s", exc)
        return None, str(exc)


def load_license(data_dir: Path) -> License | None:
    """Lisensi tersimpan (valid & belum kedaluwarsa), atau None."""
    return check_stored_license(data_dir)[0]


def save_license(data_dir: Path, lic: License) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    license_path(data_dir).write_text(lic.key + "\n", encoding="utf-8")
