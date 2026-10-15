"""Skema database SQLite (SQLAlchemy 2.0)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(50), default="Umum")
    unit: Mapped[str | None] = mapped_column(String(150))  # program studi / unit kerja
    directory_status: Mapped[str | None] = mapped_column(String(50))
    directory_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Hanya embedding yang disimpan, bukan foto wajah (minimisasi data biometrik, UU PDP)
    face_embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    visits: Mapped[list[Visit]] = relationship(back_populates="member", passive_deletes=True)


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), index=True
    )
    guest_name: Mapped[str | None] = mapped_column(String(150))
    purpose: Mapped[str | None] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(20))  # face | manual | guest
    score: Mapped[float | None] = mapped_column(Float)
    visited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    member: Mapped[Member | None] = relationship(back_populates="visits")


def create_session_factory(db_path: Path | str) -> sessionmaker:
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{db_path}"
    if url != "sqlite://":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _add_missing_columns(engine) -> None:
    """Migrasi ringan: create_all tidak menambah kolom baru ke tabel yang sudah ada."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
            for column in table.columns:
                if column.name not in existing:
                    col_type = column.type.compile(engine.dialect)
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                    )


def backup_database(src: Path, dst: Path) -> None:
    """Salinan konsisten memakai backup API SQLite (aman walau aplikasi sedang berjalan)."""
    with closing(sqlite3.connect(src)) as source, closing(sqlite3.connect(dst)) as target:
        source.backup(target)
