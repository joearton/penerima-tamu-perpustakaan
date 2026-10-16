"""Klien read-only untuk API direktori anggota (lookup berdasarkan nomor induk).

Kontrak yang diharapkan:
    GET <DIRECTORY_LOOKUP_URL dengan {nomor} terisi>
    Header: X-API-Key, X-API-Secret
    200: {"status": true, "data": {"member_no", "name", "category", "unit", "status"}}
    404: anggota tidak ditemukan; 401/403: kredensial ditolak; 429: batas laju terlampaui

Hanya field di atas yang diambil; respons mentah tidak pernah disimpan atau dicatat ke log.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from library_visitor.extensions import DirectoryPerson, ExtensionError

log = logging.getLogger(__name__)

USER_AGENT = "library-visitor/0.1"
KNOWN_CATEGORIES = ("Mahasiswa", "Dosen", "Staf")


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def person_from_api(data: dict) -> DirectoryPerson:
    category = _clean(data.get("category"))
    return DirectoryPerson(
        member_no=_clean(data.get("member_no")),
        name=_clean(data.get("name")),
        category=category if category in KNOWN_CATEGORIES else "Umum",
        unit=_clean(data.get("unit")),
        status=_clean(data.get("status")),
    )


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """Pesan singkat dari body galat server ({"detail": ...} atau {"message": ...})."""
    try:
        body = json.loads(exc.read(2000))
    except (ValueError, OSError, TypeError):
        return ""
    if not isinstance(body, dict):
        return ""
    return str(body.get("detail") or body.get("message") or "")[:200]


class ApiDirectory:
    label = "Cari di direktori"

    def __init__(self, lookup_url: str, api_key: str, api_secret: str, timeout: float = 8) -> None:
        if "{nomor}" not in lookup_url:
            raise ValueError("DIRECTORY_LOOKUP_URL harus memuat placeholder {nomor}")
        self.lookup_url = lookup_url
        self._headers = {
            "X-API-Key": api_key,
            "X-API-Secret": api_secret,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> ApiDirectory | None:
        """None bila variabel DIRECTORY_* belum diisi (fitur dinonaktifkan)."""
        url = os.environ.get("DIRECTORY_LOOKUP_URL", "").strip()
        key = os.environ.get("DIRECTORY_API_KEY", "").strip()
        secret = os.environ.get("DIRECTORY_API_SECRET", "").strip()
        if not (url and key and secret):
            return None
        return cls(url, key, secret)

    def lookup(self, number: str) -> DirectoryPerson | None:
        number = number.strip()
        if not number:
            return None
        url = self.lookup_url.replace("{nomor}", urllib.parse.quote(number, safe=""))
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403):
                detail = _error_detail(exc)
                raise ExtensionError(
                    "API key direktori ditolak"
                    + (f": {detail}" if detail else "")
                    + ". Pastikan DIRECTORY_API_KEY/SECRET di .env tersalin lengkap."
                ) from None
            if exc.code == 429:
                raise ExtensionError(
                    "Batas permintaan ke direktori terlampaui, coba lagi nanti"
                ) from None
            raise ExtensionError(f"Direktori mengembalikan HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExtensionError(f"Tidak bisa terhubung ke direktori: {exc}") from None
        except ValueError:
            raise ExtensionError("Respons direktori bukan JSON yang valid") from None
        if not body.get("status") or not body.get("data"):
            return None
        return person_from_api(body["data"])


def warn_if_env_exposed(env_path: Path) -> None:
    """File .env berisi API key: sebaiknya hanya bisa dibaca pemiliknya (chmod 600)."""
    if os.name != "posix" or not env_path.exists():
        return
    if env_path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        log.warning("%s bisa dibaca user lain; jalankan: chmod 600 %s", env_path, env_path)
