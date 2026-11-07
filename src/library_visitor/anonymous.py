"""Penghitungan pengunjung tak dikenal (anonim) tanpa menyimpan data biometrik.

Embedding wajah tak dikenal hanya disimpan di memori selama `ttl` untuk mencegah orang yang
sama terhitung berulang, lalu dibuang. Database hanya menerima kunjungan bertipe anonim
(waktu saja, tanpa nama/foto/embedding). Hasilnya perkiraan, bukan identifikasi.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from library_visitor.face import normalize

MIN_TTL_SECONDS = 120
KNOWN_MERGE_WINDOW = 60.0  # detik: catatan anonim sebelum wajah dikenali dianggap orang itu


@dataclass
class _Pending:
    """Wajah tak dikenal yang sedang dikonfirmasi (harus terlihat beberapa frame berturut-turut)."""

    embedding: np.ndarray
    frames: int = 1


@dataclass
class _Seen:
    """Wajah anonim yang sudah tercatat (atau sudah diklaim oleh scan kartu/tamu)."""

    embedding: np.ndarray
    last_seen: float
    visit_id: int | None = None  # None = diklaim; tidak akan dihitung lagi selama ttl
    recorded_at: float = 0.0  # kapan kunjungan anonimnya dicatat


class AnonymousTracker:
    """Thread-safe agar aman dipakai bersama halaman Kunjungan dan jendela kios."""

    def __init__(self, ttl_seconds: float, same_threshold: float, min_frames: int) -> None:
        self.ttl = max(ttl_seconds, MIN_TTL_SECONDS)
        self.same_threshold = same_threshold
        self.min_frames = min_frames
        self._lock = threading.Lock()
        self._pending: list[_Pending] = []
        self._seen: list[_Seen] = []
        self._nearest: tuple[np.ndarray, float] | None = None  # wajah tak dikenal terdekat terakhir

    def __len__(self) -> int:
        return len(self._seen)

    def configure(self, ttl_seconds: float, same_threshold: float, min_frames: int) -> None:
        with self._lock:
            # Minimal 2 menit: dengan jeda catat ulang 0, orang yang sama akan terhitung
            # anonim berulang kali setiap beberapa frame.
            self.ttl = max(ttl_seconds, MIN_TTL_SECONDS)
            self.same_threshold, self.min_frames = same_threshold, min_frames

    def observe(self, embeddings: list[np.ndarray], now: float) -> list[np.ndarray]:
        """Proses wajah tak dikenal di satu frame (urut terdekat dulu).

        Mengembalikan embedding pengunjung anonim BARU yang harus dicatat; panggil
        `attach()` dengan id kunjungan yang dibuat agar bisa digabung dengan scan kartu.
        """
        with self._lock:
            self._expire(now)
            embeddings = [normalize(e) for e in embeddings]
            if embeddings:
                self._nearest = (embeddings[0], now)

            still_pending: list[_Pending] = []
            ready: list[np.ndarray] = []
            for emb in embeddings:
                seen = self._find_seen(emb)
                if seen is not None:
                    seen.last_seen = now  # masih orang yang sama: perpanjang, jangan hitung
                    continue
                pending = self._best(self._pending, emb)
                if pending is None:
                    still_pending.append(_Pending(emb))
                    continue
                self._pending.remove(pending)
                pending.frames += 1
                pending.embedding = normalize(pending.embedding + emb)
                if pending.frames >= self.min_frames:
                    ready.append(pending.embedding)
                else:
                    still_pending.append(pending)
            # Kandidat yang tidak terlihat di frame ini gugur (harus berturut-turut)
            self._pending = still_pending
            return ready

    def attach(self, embedding: np.ndarray, visit_id: int, now: float) -> None:
        with self._lock:
            self._seen.append(_Seen(normalize(embedding), now, visit_id, recorded_at=now))

    def mark_known(self, embeddings: list[np.ndarray], now: float) -> list[int]:
        """Wajah yang baru dikenali sebagai anggota: jangan dihitung anonim selama ttl.

        Tanpa ini, anggota yang tetap di depan kamera dan skornya sempat turun (pose, cahaya)
        ikut terhitung anonim. Bila wajah itu sudah terlanjur dicatat anonim dalam
        `KNOWN_MERGE_WINDOW` detik terakhir, id kunjungan anonimnya dikembalikan untuk dihapus.
        """
        stale: list[int] = []
        with self._lock:
            self._expire(now)
            for emb in (normalize(e) for e in embeddings):
                pending = self._best(self._pending, emb)
                if pending is not None:
                    self._pending.remove(pending)
                seen = self._find_seen(emb)
                if seen is None:
                    self._seen.append(_Seen(emb, now, None))
                    continue
                if seen.visit_id is not None and now - seen.recorded_at <= KNOWN_MERGE_WINDOW:
                    stale.append(seen.visit_id)
                seen.visit_id, seen.last_seen = None, now
        return stale

    def claim_recent(self, now: float, window: float = 20.0) -> int | None:
        """Wajah tak dikenal terdekat dalam `window` detik terakhir ternyata anggota/tamu.

        Mencegah pencatatan ganda: wajah itu tidak akan dihitung anonim selama ttl.
        Mengembalikan id kunjungan anonim yang sudah terlanjur dicatat (untuk dihapus), bila ada.
        """
        with self._lock:
            if self._nearest is None or now - self._nearest[1] > window:
                return None
            emb = self._nearest[0]
            self._nearest = None
            pending = self._best(self._pending, emb)
            if pending is not None:
                self._pending.remove(pending)
            seen = self._find_seen(emb)
            if seen is None:
                self._seen.append(_Seen(emb, now, None))
                return None
            visit_id, seen.visit_id, seen.last_seen = seen.visit_id, None, now
            return visit_id

    def reset(self) -> None:
        with self._lock:
            self._pending.clear()
            self._seen.clear()
            self._nearest = None

    # ---------- internal (dipanggil dengan lock) ----------

    def _expire(self, now: float) -> None:
        self._seen = [s for s in self._seen if now - s.last_seen <= self.ttl]

    def _find_seen(self, emb: np.ndarray) -> _Seen | None:
        return self._best(self._seen, emb)

    def _best(self, items: list, emb: np.ndarray):
        best, best_score = None, self.same_threshold
        for item in items:
            score = float(item.embedding @ emb)
            if score >= best_score:
                best, best_score = item, score
        return best
