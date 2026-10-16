"""Klien read-only untuk API direktori anggota.

Kontrak yang diharapkan (header X-API-Key dan X-API-Secret pada semua permintaan):

    Lookup (wajib)   GET <DIRECTORY_LOOKUP_URL dengan {nomor} terisi>
        200: {"status": true, "data": {"member_no", "name", "category", "unit", "status"}}
    Pencarian (opsional, untuk auto-complete)   GET <DIRECTORY_SEARCH_URL>?q=<teks>&limit=<n>
        200: {"status": true, "data": [<objek anggota seperti di atas>, ...]}
    Foto (opsional, untuk tebakan wajah saat registrasi)
        GET <DIRECTORY_FACES_URL>?page=<n>&per_page=<n>[&updated_since=<ISO8601>]
        200: {"status": true, "data": [<objek anggota> + "photo" (JPEG base64)
              + "photo_updated_at"], "meta": {"current_page", "last_page", "total"}}

    404: tidak ditemukan; 401/403: kredensial ditolak; 429: batas laju terlampaui.

Hanya field di atas yang diambil; respons mentah tidak pernah disimpan atau dicatat ke log.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from library_visitor.extensions import DirectoryPerson, DirectoryPhoto, ExtensionError

log = logging.getLogger(__name__)

USER_AGENT = "library-visitor/0.1"
KNOWN_CATEGORIES = ("Mahasiswa", "Dosen", "Staf")
MIN_SEARCH_CHARS = 3
FACES_PER_PAGE = 100


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


def _with_query(url: str, params: dict) -> str:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{url}{'&' if '?' in url else '?'}{query}" if query else url


class ApiDirectory:
    label = "Cari di direktori"

    def __init__(
        self,
        lookup_url: str,
        api_key: str,
        api_secret: str,
        search_url: str = "",
        faces_url: str = "",
        timeout: float = 8,
    ) -> None:
        if "{nomor}" not in lookup_url:
            raise ValueError("DIRECTORY_LOOKUP_URL harus memuat placeholder {nomor}")
        self.lookup_url = lookup_url
        self.search_url = search_url
        self.faces_url = faces_url
        self._headers = {
            "X-API-Key": api_key,
            "X-API-Secret": api_secret,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> ApiDirectory | None:
        """None bila variabel DIRECTORY_* wajib belum diisi (fitur dinonaktifkan)."""
        url = os.environ.get("DIRECTORY_LOOKUP_URL", "").strip()
        key = os.environ.get("DIRECTORY_API_KEY", "").strip()
        secret = os.environ.get("DIRECTORY_API_SECRET", "").strip()
        if not (url and key and secret):
            return None
        return cls(
            url,
            key,
            secret,
            search_url=os.environ.get("DIRECTORY_SEARCH_URL", "").strip(),
            faces_url=os.environ.get("DIRECTORY_FACES_URL", "").strip(),
        )

    @property
    def supports_search(self) -> bool:
        return bool(self.search_url)

    @property
    def supports_faces(self) -> bool:
        return bool(self.faces_url)

    # ---------- HTTP ----------

    def _get(self, url: str, timeout: float | None = None) -> dict | None:
        """Body JSON, atau None bila 404."""
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self._timeout) as resp:
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
        return body if isinstance(body, dict) else None

    # ---------- operasi ----------

    def lookup(self, number: str) -> DirectoryPerson | None:
        number = number.strip()
        if not number:
            return None
        body = self._get(self.lookup_url.replace("{nomor}", urllib.parse.quote(number, safe="")))
        if not body or not body.get("status") or not isinstance(body.get("data"), dict):
            return None
        return person_from_api(body["data"])

    def search(self, text: str, limit: int = 10) -> list[DirectoryPerson]:
        text = text.strip()
        if not self.supports_search or len(text) < MIN_SEARCH_CHARS:
            return []
        body = self._get(_with_query(self.search_url, {"q": text, "limit": limit}))
        items = body.get("data") if body and body.get("status") else None
        if not isinstance(items, list):
            return []
        return [person_from_api(item) for item in items[:limit] if isinstance(item, dict)]

    def iter_photos(self, updated_since: str | None = None) -> Iterator[DirectoryPhoto]:
        """Semua foto (halaman demi halaman). Item tanpa foto yang valid dilewati."""
        if not self.supports_faces:
            return
        page = 1
        while True:
            url = _with_query(
                self.faces_url,
                {"page": page, "per_page": FACES_PER_PAGE, "updated_since": updated_since},
            )
            body = self._get(url, timeout=max(self._timeout, 30))
            items = body.get("data") if body and body.get("status") else None
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict) or not item.get("photo"):
                    continue
                try:
                    jpeg = base64.b64decode(item["photo"], validate=True)
                except (binascii.Error, ValueError):
                    continue
                yield DirectoryPhoto(
                    person_from_api(item), jpeg, _clean(item.get("photo_updated_at"))
                )
            meta = body.get("meta") or {}
            if not items or page >= int(meta.get("last_page") or page):
                return
            page += 1


def warn_if_env_exposed(env_path: Path) -> None:
    """File .env berisi API key: sebaiknya hanya bisa dibaca pemiliknya (chmod 600)."""
    if os.name != "posix" or not env_path.exists():
        return
    if env_path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        log.warning("%s bisa dibaca user lain; jalankan: chmod 600 %s", env_path, env_path)
