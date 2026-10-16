from datetime import date, timedelta

from library_visitor.backups import backup_dir, list_backups, run_daily_backup
from library_visitor.config import Settings
from library_visitor.db import create_session_factory
from library_visitor.face import FaceMatcher
from library_visitor.services import VisitorService


def make_settings(tmp_path, **values) -> Settings:
    s = Settings(home=tmp_path)
    s.update(values)
    svc = VisitorService(create_session_factory(s.database_path), FaceMatcher(0.4), 30)
    svc.record_guest_visit("Tamu", "Riset")
    return s


def test_daily_backup_once_per_day_with_rotation(tmp_path):
    s = make_settings(tmp_path, backup_keep=3)
    start = date(2026, 10, 1)
    assert run_daily_backup(s, start) is not None
    assert run_daily_backup(s, start) is None  # hari yang sama: tidak dobel
    for i in range(1, 6):
        run_daily_backup(s, start + timedelta(days=i))
    names = [p.name for p in list_backups(backup_dir(s))]
    assert names == [
        "library_visitor_20261006.db",
        "library_visitor_20261005.db",
        "library_visitor_20261004.db",
    ]
    assert not list(backup_dir(s).glob("*.part"))


def test_backup_is_valid_database_and_custom_dir(tmp_path):
    target = tmp_path / "flashdisk"
    s = make_settings(tmp_path, backup_dir=str(target))
    created = run_daily_backup(s, date(2026, 10, 1))
    assert created.parent == target
    restored = VisitorService(create_session_factory(created), FaceMatcher(0.4), 30)
    assert restored.count_between(date(2000, 1, 1), date(2100, 1, 1)) == 1


def test_disabled(tmp_path):
    s = make_settings(tmp_path, auto_backup_enabled=False)
    assert run_daily_backup(s) is None
    assert list_backups(backup_dir(s)) == []
