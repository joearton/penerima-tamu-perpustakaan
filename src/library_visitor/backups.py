"""Backup harian otomatis database dengan rotasi (menyimpan N salinan terakhir)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from library_visitor.config import Settings
from library_visitor.db import backup_database

log = logging.getLogger(__name__)

PREFIX = "library_visitor_"


def backup_dir(settings: Settings) -> Path:
    return Path(settings.backup_dir) if settings.backup_dir else settings.data_dir / "backups"


def list_backups(directory: Path) -> list[Path]:
    """Backup otomatis, terbaru dulu (nama file memuat tanggal, jadi urut leksikal = kronologis)."""
    if not directory.exists():
        return []
    return sorted(directory.glob(f"{PREFIX}????????.db"), reverse=True)


def run_daily_backup(settings: Settings, today: date | None = None) -> Path | None:
    """Buat backup hari ini bila belum ada, lalu hapus yang melebihi `backup_keep`.

    Mengembalikan path backup baru, atau None bila tidak ada yang dibuat.
    """
    if not settings.auto_backup_enabled or not settings.database_path.exists():
        return None
    directory = backup_dir(settings)
    target = directory / f"{PREFIX}{(today or date.today()):%Y%m%d}.db"
    created = None
    if not target.exists():
        directory.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        backup_database(settings.database_path, tmp)
        tmp.replace(target)
        created = target
        log.info("Backup otomatis dibuat: %s", target)
    for old in list_backups(directory)[max(1, settings.backup_keep) :]:
        old.unlink(missing_ok=True)
        log.info("Backup lama dihapus: %s", old.name)
    return created
