"""Galeri wajah dari foto direktori, untuk menebak identitas saat registrasi.

Foto dari direktori hanya diproses di memori menjadi embedding lalu dibuang; yang disimpan
hanya embedding dan data minimal (nomor, nama, kategori, unit, status).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from library_visitor.db import DirectoryFace
from library_visitor.extensions import DirectoryPerson, ExtensionError, MemberDirectory
from library_visitor.face import FaceEngine, FaceMatcher
from library_visitor.services import from_bytes, to_bytes

log = logging.getLogger(__name__)

# Wajah di foto profil lebih kecil dari ini (piksel) dianggap tidak layak dijadikan acuan
MIN_PHOTO_FACE = 40


@dataclass(frozen=True)
class Candidate:
    person: DirectoryPerson
    score: float


def split_list(text: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in text.split(",") if x.strip())


@dataclass(frozen=True)
class GalleryFilter:
    """Syarat orang yang boleh masuk galeri; nilai kosong = tidak membatasi."""

    categories: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    status: str = ""

    @classmethod
    def from_settings(cls, settings) -> GalleryFilter:
        return cls(
            split_list(settings.gallery_categories),
            split_list(settings.gallery_prefixes),
            settings.gallery_status.strip(),
        )

    def accepts(self, person: DirectoryPerson) -> bool:
        if self.categories and person.category.lower() not in {c.lower() for c in self.categories}:
            return False
        if self.prefixes and not person.member_no.startswith(self.prefixes):
            return False
        return not self.status or person.status.lower() == self.status.lower()


@dataclass
class SyncStats:
    added: int = 0
    skipped: int = 0  # foto tidak terbaca / tidak ada wajah
    filtered: int = 0  # tidak memenuhi filter galeri
    total: int = 0


class FaceGallery:
    """Thread-safe: dibaca dari UI, diisi dari thread sinkron."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory
        self._matcher = FaceMatcher(threshold=0.0)
        self._lock = threading.Lock()
        self._ids: dict[str, int] = {}  # member_no -> id internal matcher
        self._people: dict[int, DirectoryPerson] = {}

    def __len__(self) -> int:
        return len(self._matcher)

    def load(self) -> int:
        with self._sessions() as s:
            rows = list(s.scalars(select(DirectoryFace)))
        with self._lock:
            self._ids.clear()
            self._people.clear()
            items = []
            for i, row in enumerate(rows):
                self._ids[row.member_no] = i
                self._people[i] = _person(row)
                items.append((i, row.member_no, from_bytes(row.embedding)))
            self._matcher.load(items)
        return len(rows)

    def top(self, embedding: np.ndarray, k: int, min_score: float) -> list[Candidate]:
        with self._lock:
            return [
                Candidate(self._people[m.member_id], m.score)
                for m in self._matcher.top(embedding, k)
                if m.score >= min_score and m.member_id in self._people
            ]

    def upsert(self, person: DirectoryPerson, embedding: np.ndarray, photo_updated_at: str) -> None:
        with self._sessions.begin() as s:
            row = s.get(DirectoryFace, person.member_no) or DirectoryFace(
                member_no=person.member_no
            )
            row.name, row.category = person.name, person.category
            row.unit, row.status = person.unit or None, person.status or None
            row.embedding = to_bytes(embedding)
            row.photo_updated_at = photo_updated_at or None
            row.synced_at = datetime.now()
            s.add(row)
        with self._lock:
            idx = self._ids.setdefault(person.member_no, len(self._ids))
            self._people[idx] = person
            self._matcher.upsert(idx, person.member_no, embedding)

    def clear(self) -> None:
        with self._sessions.begin() as s:
            s.execute(delete(DirectoryFace))
        with self._lock:
            self._ids.clear()
            self._people.clear()
            self._matcher.load([])

    def last_photo_update(self) -> str | None:
        with self._sessions() as s:
            return s.scalar(select(func.max(DirectoryFace.photo_updated_at)))

    def last_synced_at(self) -> datetime | None:
        with self._sessions() as s:
            return s.scalar(select(func.max(DirectoryFace.synced_at)))


def _person(row: DirectoryFace) -> DirectoryPerson:
    return DirectoryPerson(row.member_no, row.name, row.category, row.unit or "", row.status or "")


def embed_photo(engine: FaceEngine, jpeg: bytes) -> np.ndarray | None:
    """Embedding wajah terbesar di foto, atau None bila foto tidak terbaca / tanpa wajah."""
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    faces = engine.detect(image)
    if not faces or faces[0].size < MIN_PHOTO_FACE:
        return None
    return engine.embed(image, faces[0])


def sync_gallery(
    directory: MemberDirectory,
    gallery: FaceGallery,
    models_dir: Path,
    full: bool = False,
    gallery_filter: GalleryFilter | None = None,
    progress: Callable[[SyncStats], None] | None = None,
    cancelled: threading.Event | None = None,
) -> SyncStats:
    """Unduh foto direktori dan perbarui galeri. Jalankan di thread latar.

    `full=True` mengosongkan galeri dulu (membuang orang yang sudah tidak memenuhi syarat);
    selain itu hanya foto yang berubah sejak sinkron terakhir.
    """
    if not getattr(directory, "supports_faces", False):
        raise ExtensionError("Direktori tidak menyediakan foto (DIRECTORY_FACES_URL kosong)")
    engine = FaceEngine(models_dir, score_threshold=0.6)
    if full:
        gallery.clear()
    since = None if full else gallery.last_photo_update()
    stats = SyncStats()
    for photo in directory.iter_photos(updated_since=since):
        if cancelled is not None and cancelled.is_set():
            break
        stats.total += 1
        if gallery_filter is not None and not gallery_filter.accepts(photo.person):
            stats.filtered += 1
            continue
        embedding = embed_photo(engine, photo.jpeg)
        if embedding is None:
            stats.skipped += 1
        else:
            gallery.upsert(photo.person, embedding, photo.updated_at)
            stats.added += 1
        if progress is not None and stats.total % 20 == 0:
            progress(stats)
    log.info(
        "Sinkron galeri foto (%s): %d diproses, %d ditambahkan/diperbarui, %d tanpa wajah, "
        "%d tidak lolos filter",
        "penuh" if full else "inkremental",
        stats.total,
        stats.added,
        stats.skipped,
        stats.filtered,
    )
    return stats
