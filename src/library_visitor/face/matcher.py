"""Pencocokan embedding terhadap anggota terdaftar (in-memory, cosine similarity)."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from library_visitor.face.engine import normalize

EMBEDDING_DIM = 128


@dataclass(frozen=True)
class Match:
    member_id: int
    label: str
    score: float


class FaceMatcher:
    """Dibaca dari thread kamera dan diubah dari thread UI, jadi dilindungi lock."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self._lock = threading.Lock()
        self._ids: list[int] = []
        self._labels: list[str] = []
        self._matrix = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    def __len__(self) -> int:
        return len(self._ids)

    def load(self, items: Iterable[tuple[int, str, np.ndarray]]) -> None:
        items = list(items)
        with self._lock:
            self._ids = [i for i, _, _ in items]
            self._labels = [label for _, label, _ in items]
            self._matrix = (
                np.stack([normalize(e) for _, _, e in items])
                if items
                else np.empty((0, EMBEDDING_DIM), dtype=np.float32)
            )

    def upsert(self, member_id: int, label: str, embedding: np.ndarray) -> None:
        emb = normalize(embedding)
        with self._lock:
            if member_id in self._ids:
                idx = self._ids.index(member_id)
                self._labels[idx] = label
                self._matrix[idx] = emb
            else:
                self._ids.append(member_id)
                self._labels.append(label)
                self._matrix = np.vstack([self._matrix, emb])

    def remove(self, member_id: int) -> None:
        with self._lock:
            if member_id not in self._ids:
                return
            idx = self._ids.index(member_id)
            del self._ids[idx]
            del self._labels[idx]
            self._matrix = np.delete(self._matrix, idx, axis=0)

    def best(self, embedding: np.ndarray, exclude: int | None = None) -> Match | None:
        """Kandidat terdekat tanpa memperhatikan ambang."""
        with self._lock:
            if not self._ids:
                return None
            scores = self._matrix @ normalize(embedding)
            if exclude is not None and exclude in self._ids:
                scores[self._ids.index(exclude)] = -1.0
            idx = int(np.argmax(scores))
            if scores[idx] < 0:
                return None
            return Match(self._ids[idx], self._labels[idx], float(scores[idx]))

    def match(self, embedding: np.ndarray) -> Match | None:
        best = self.best(embedding)
        return best if best and best.score >= self.threshold else None
