"""Logika bisnis: registrasi anggota, pencatatan kunjungan, dan query laporan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, sessionmaker

from library_visitor.db import Member, Visit
from library_visitor.face import FaceMatcher, normalize

CATEGORIES = ("Mahasiswa", "Dosen", "Staf", "Umum")


class ServiceError(Exception):
    pass


@dataclass(frozen=True)
class VisitResult:
    visit: Visit | None  # None berarti masih dalam masa cooldown
    member: Member


def to_bytes(embedding: np.ndarray) -> bytes:
    return normalize(embedding).astype(np.float32).tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()


def day_range(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


class VisitorService:
    def __init__(self, session_factory: sessionmaker, matcher: FaceMatcher, cooldown_minutes: int):
        self._sessions = session_factory
        self.matcher = matcher
        self.cooldown = timedelta(minutes=cooldown_minutes)

    # ---------- anggota ----------

    def load_matcher(self) -> int:
        with self._sessions() as s:
            rows = s.execute(
                select(Member.id, Member.name, Member.face_embedding).where(
                    Member.face_embedding.is_not(None)
                )
            ).all()
        self.matcher.load((mid, name, from_bytes(blob)) for mid, name, blob in rows)
        return len(rows)

    def get_member_by_no(self, member_no: str) -> Member | None:
        with self._sessions() as s:
            return s.scalar(select(Member).where(Member.member_no == member_no.strip()))

    def save_member(
        self,
        member_no: str,
        name: str,
        category: str,
        embeddings: list[np.ndarray] | None = None,
        unit: str | None = None,
        directory_status: str | None = None,
    ) -> Member:
        """Buat anggota baru atau perbarui yang sudah ada (berdasarkan no. anggota).

        `directory_status` diisi hanya bila data berasal dari direktori; menandai waktu sinkron.
        """
        member_no, name = member_no.strip(), name.strip()
        if not member_no or not name:
            raise ServiceError("No. anggota dan nama wajib diisi")
        with self._sessions.begin() as s:
            member = s.scalar(select(Member).where(Member.member_no == member_no))
            if member is None:
                member = Member(member_no=member_no)
                s.add(member)
            member.name = name
            member.category = category
            if unit is not None:
                member.unit = unit.strip() or None
            if directory_status is not None:
                member.directory_status = directory_status
                member.directory_synced_at = datetime.now()
            if embeddings:
                member.face_embedding = to_bytes(np.mean([normalize(e) for e in embeddings], 0))
                member.consent_at = datetime.now()
            s.flush()
        if member.face_embedding is not None:
            self.matcher.upsert(member.id, member.name, from_bytes(member.face_embedding))
        return member

    def delete_face(self, member_id: int) -> None:
        with self._sessions.begin() as s:
            member = s.get(Member, member_id)
            if member:
                member.face_embedding = None
                member.consent_at = None
        self.matcher.remove(member_id)

    def delete_member(self, member_id: int) -> None:
        """Hapus anggota; riwayat kunjungan tetap ada tetapi dianonimkan (member_id = NULL)."""
        with self._sessions.begin() as s:
            member = s.get(Member, member_id)
            if member:
                s.delete(member)
        self.matcher.remove(member_id)

    def list_members(self, search: str = "", limit: int | None = None) -> list[Member]:
        stmt = select(Member).order_by(Member.name)
        if search:
            like = f"%{search.strip()}%"
            stmt = stmt.where(or_(Member.name.ilike(like), Member.member_no.ilike(like)))
        if limit:
            stmt = stmt.limit(limit)
        with self._sessions() as s:
            return list(s.scalars(stmt))

    # ---------- kunjungan ----------

    def record_member_visit(
        self, member_id: int, method: str, score: float | None = None
    ) -> VisitResult:
        now = datetime.now()
        with self._sessions.begin() as s:
            member = s.get(Member, member_id)
            if member is None:
                raise ServiceError("Anggota tidak ditemukan")
            last = s.scalar(select(func.max(Visit.visited_at)).where(Visit.member_id == member_id))
            if last and now - last < self.cooldown:
                return VisitResult(None, member)
            visit = Visit(member_id=member_id, method=method, score=score, visited_at=now)
            s.add(visit)
        return VisitResult(visit, member)

    def record_manual_visit(self, member_no: str) -> VisitResult:
        member = self.get_member_by_no(member_no)
        if member is None:
            raise ServiceError(f"No. anggota '{member_no}' tidak terdaftar")
        return self.record_member_visit(member.id, "manual")

    def record_guest_visit(self, name: str, purpose: str = "") -> Visit:
        if not name.strip():
            raise ServiceError("Nama tamu wajib diisi")
        with self._sessions.begin() as s:
            visit = Visit(guest_name=name.strip(), purpose=purpose.strip() or None, method="guest")
            s.add(visit)
        return visit

    def record_anonymous_visit(self) -> Visit:
        """Pengunjung tak dikenal: hanya waktu yang dicatat (tanpa nama/foto/biometrik)."""
        with self._sessions.begin() as s:
            visit = Visit(method="anonymous")
            s.add(visit)
        return visit

    def delete_visit(self, visit_id: int) -> None:
        with self._sessions.begin() as s:
            visit = s.get(Visit, visit_id)
            if visit is not None:
                s.delete(visit)

    def visits_between(self, start: date, end: date) -> list[Visit]:
        lo, hi = day_range(start, end)
        with self._sessions() as s:
            return list(
                s.scalars(
                    select(Visit)
                    .options(joinedload(Visit.member))
                    .where(Visit.visited_at >= lo, Visit.visited_at < hi)
                    .order_by(Visit.visited_at.desc())
                )
            )

    def count_between(self, start: date, end: date) -> int:
        lo, hi = day_range(start, end)
        with self._sessions() as s:
            return s.scalar(
                select(func.count(Visit.id)).where(Visit.visited_at >= lo, Visit.visited_at < hi)
            )


def visitor_name(visit: Visit) -> str:
    if visit.member is not None:
        return visit.member.name
    if visit.method == "anonymous":
        return "Pengunjung anonim"
    return visit.guest_name or "(anggota terhapus)"


def visit_category(visit: Visit) -> str:
    if visit.member is not None:
        return visit.member.category
    return "Anonim" if visit.method == "anonymous" else "Tamu"
