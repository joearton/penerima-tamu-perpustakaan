from datetime import date, timedelta

import numpy as np
import pytest

from library_visitor.config import Settings
from library_visitor.db import create_session_factory
from library_visitor.face import FaceMatcher, normalize
from library_visitor.face.models import missing_models
from library_visitor.reports import export_excel
from library_visitor.services import ServiceError, VisitorService


def rand_emb(seed: int) -> np.ndarray:
    return normalize(np.random.default_rng(seed).normal(size=128))


@pytest.fixture
def service() -> VisitorService:
    return VisitorService(create_session_factory(":memory:"), FaceMatcher(0.4), 30)


def test_matcher_matches_and_rejects():
    m = FaceMatcher(0.4)
    m.load([(1, "Ani", rand_emb(1)), (2, "Budi", rand_emb(2))])
    noisy = normalize(rand_emb(1) + 0.05 * rand_emb(99))
    assert m.match(noisy).member_id == 1
    assert m.match(rand_emb(3)) is None
    m.remove(1)
    assert m.match(noisy) is None
    assert len(m) == 1


def test_save_member_updates_matcher_and_reload(service):
    member = service.save_member("A01", "Ani", "Mahasiswa", [rand_emb(1), rand_emb(1)])
    assert service.matcher.match(rand_emb(1)).member_id == member.id
    service.matcher.load([])
    assert service.load_matcher() == 1
    # Simpan ulang dengan no. anggota sama = update, bukan anggota baru
    service.save_member("A01", "Ani Lestari", "Dosen")
    assert [m.name for m in service.list_members()] == ["Ani Lestari"]


def test_visit_cooldown(service):
    member = service.save_member("A01", "Ani", "Mahasiswa", [rand_emb(1)])
    assert service.record_member_visit(member.id, "face", 0.8).visit is not None
    assert service.record_member_visit(member.id, "face", 0.8).visit is None
    assert service.record_manual_visit("A01").visit is None
    with pytest.raises(ServiceError):
        service.record_manual_visit("TIDAK-ADA")


def test_delete_member_anonymizes_visits(service, tmp_path):
    member = service.save_member("A01", "Ani", "Mahasiswa", [rand_emb(1)])
    service.record_member_visit(member.id, "face", 0.8)
    service.record_guest_visit("Tamu", "Riset")
    service.delete_member(member.id)
    today = date.today()
    visits = service.visits_between(today, today)
    assert len(visits) == 2 and all(v.member is None for v in visits)
    assert service.matcher.match(rand_emb(1)) is None
    assert service.count_between(today - timedelta(days=1), today) == 2
    assert export_excel(service, today, today, tmp_path / "r.xlsx") == 2


settings = Settings()


@pytest.mark.skipif(bool(missing_models(settings.models_dir)), reason="model belum diunduh")
def test_engine_loads_and_handles_empty_frame():
    from library_visitor.face import FaceEngine

    engine = FaceEngine(settings.models_dir)
    assert engine.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []
