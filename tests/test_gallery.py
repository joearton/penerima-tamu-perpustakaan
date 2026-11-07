import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from library_visitor import gallery as gallery_mod  # noqa: E402
from library_visitor.db import create_session_factory  # noqa: E402
from library_visitor.extensions import DirectoryPerson, DirectoryPhoto, ExtensionError  # noqa: E402
from library_visitor.face import normalize  # noqa: E402
from library_visitor.gallery import FaceGallery, GalleryFilter, sync_gallery  # noqa: E402


def emb(seed):
    return normalize(np.random.default_rng(seed).normal(size=128))


def person(no, status="Aktif", category="Mahasiswa"):
    return DirectoryPerson(no, f"Orang {no}", category, "Informatika", status)


def test_gallery_top_upsert_clear_and_persistence(tmp_path):
    sessions = create_session_factory(tmp_path / "db.sqlite")
    g = FaceGallery(sessions)
    g.upsert(person("2301"), emb(1), "2026-10-01")
    g.upsert(person("2302"), emb(2), "2026-10-02")
    g.upsert(person("2301"), emb(1), "2026-10-03")  # update, bukan duplikat
    assert len(g) == 2
    noisy = normalize(emb(1) + 0.1 * emb(9))
    top = g.top(noisy, k=2, min_score=0.0)
    assert top[0].person.member_no == "2301" and top[0].score > top[1].score
    assert g.top(noisy, k=3, min_score=0.999) == []
    assert g.last_photo_update() == "2026-10-03"

    reloaded = FaceGallery(sessions)
    assert reloaded.load() == 2
    assert reloaded.top(noisy, 1, 0.0)[0].person.name == "Orang 2301"
    reloaded.clear()
    assert len(reloaded) == 0 and FaceGallery(sessions).load() == 0


def test_gallery_filter():
    f = GalleryFilter(("Mahasiswa",), ("23", "24", "25", "26"), "Aktif")
    assert f.accepts(person("2512345"))
    assert not f.accepts(person("2212345"))  # angkatan di luar rentang
    assert not f.accepts(person("2512345", status="Cuti"))
    assert not f.accepts(person("2512345", category="Dosen"))
    assert GalleryFilter().accepts(person("1999"))  # tanpa filter


class FakeDirectory:
    supports_faces = True

    def __init__(self, photos):
        self.photos = photos
        self.since = "belum dipanggil"

    def iter_photos(self, updated_since=None):
        self.since = updated_since
        yield from self.photos


def test_sync_filters_skips_and_is_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(gallery_mod, "FaceEngine", lambda *a, **k: None)
    monkeypatch.setattr(
        gallery_mod,
        "embed_photo",
        lambda engine, jpeg: None if jpeg == b"tanpa-wajah" else emb(int(jpeg)),
    )
    g = FaceGallery(create_session_factory(tmp_path / "db.sqlite"))
    photos = [
        DirectoryPhoto(person("2501"), b"1", "2026-10-01"),
        DirectoryPhoto(person("2502"), b"tanpa-wajah", "2026-10-02"),
        DirectoryPhoto(person("2201"), b"3", "2026-10-03"),  # tidak lolos filter awalan
    ]
    gfilter = GalleryFilter(("Mahasiswa",), ("23", "24", "25", "26"), "Aktif")
    directory = FakeDirectory(photos)
    stats = sync_gallery(directory, g, tmp_path, gallery_filter=gfilter)
    assert (stats.total, stats.added, stats.skipped, stats.filtered) == (3, 1, 1, 1)
    assert directory.since is None and len(g) == 1

    directory2 = FakeDirectory([])
    sync_gallery(directory2, g, tmp_path, gallery_filter=gfilter)
    # inkremental dari foto terbaru yang sudah diproses (termasuk yang tidak lolos filter)
    assert directory2.since == "2026-10-03"

    directory3 = FakeDirectory([])
    sync_gallery(directory3, g, tmp_path, full=True)
    assert directory3.since is None and len(g) == 0  # penuh: orang yang tidak ada dibuang


class FailingDirectory(FakeDirectory):
    """Gagal setelah beberapa foto, seperti jaringan putus di tengah paginasi."""

    def __init__(self, photos, fail_after):
        super().__init__(photos)
        self.fail_after = fail_after

    def iter_photos(self, updated_since=None):
        self.since = updated_since
        for i, photo in enumerate(self.photos):
            if i == self.fail_after:
                raise ExtensionError("Tidak bisa terhubung ke direktori")
            yield photo


def test_interrupted_sync_keeps_gallery_and_watermark(tmp_path, monkeypatch):
    monkeypatch.setattr(gallery_mod, "FaceEngine", lambda *a, **k: None)
    monkeypatch.setattr(gallery_mod, "embed_photo", lambda engine, jpeg: emb(int(jpeg)))
    g = FaceGallery(create_session_factory(tmp_path / "db.sqlite"))
    first = [DirectoryPhoto(person(f"250{i}"), str(i).encode(), f"2026-10-0{i}") for i in (1, 2)]
    sync_gallery(FakeDirectory(first), g, tmp_path)
    assert len(g) == 2 and g.sync_watermark() == "2026-10-02"

    # API tidak urut waktu: halaman pertama berisi foto terbaru, lalu putus
    later = [
        DirectoryPhoto(person("2509"), b"9", "2026-10-09"),
        DirectoryPhoto(person("2503"), b"3", "2026-10-03"),
    ]
    with pytest.raises(ExtensionError):
        sync_gallery(FailingDirectory(later, fail_after=1), g, tmp_path)
    assert g.sync_watermark() == "2026-10-02"  # tidak maju: 2503 tidak akan terlewat

    retry = FakeDirectory(later)
    sync_gallery(retry, g, tmp_path)
    assert retry.since == "2026-10-02" and len(g) == 4

    # Sinkron penuh yang gagal tidak boleh mengosongkan galeri
    with pytest.raises(ExtensionError):
        sync_gallery(FailingDirectory(later, fail_after=0), g, tmp_path, full=True)
    assert len(g) == 4

    # Dibatalkan pengguna: penanda juga tidak maju
    cancelled = threading.Event()
    cancelled.set()
    newer = [DirectoryPhoto(person("2510"), b"10", "2026-10-20")]
    sync_gallery(FakeDirectory(newer), g, tmp_path, cancelled=cancelled)
    assert g.sync_watermark() == "2026-10-09" and len(g) == 4


def test_sync_requires_faces_support(tmp_path):
    g = FaceGallery(create_session_factory(tmp_path / "db.sqlite"))

    class NoFaces:
        supports_faces = False

    with pytest.raises(ExtensionError):
        sync_gallery(NoFaces(), g, tmp_path)
