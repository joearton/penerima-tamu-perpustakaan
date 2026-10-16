import base64
import json
import urllib.error
from io import BytesIO

import pytest

from library_visitor import directory_api
from library_visitor.directory_api import ApiDirectory
from library_visitor.extensions import DirectoryPerson, ExtensionError

URL = "https://directory.example/api/members/{nomor}/"


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(routes, seen):
    def urlopen(req, timeout):
        seen.append(req)
        if req.full_url not in routes:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        code, data = routes[req.full_url]
        if code != 200:
            fp = BytesIO(json.dumps(data).encode()) if data else None
            raise urllib.error.HTTPError(req.full_url, code, "err", {}, fp)
        body = {"status": True, "message": "Success", "data": data}
        return FakeResponse(json.dumps(body).encode())

    return urlopen


@pytest.fixture
def directory():
    return ApiDirectory(URL, "k" * 64, "rahasia")


def test_lookup_maps_minimal_fields(directory, monkeypatch):
    seen = []
    data = {
        "member_no": "0011223344",
        "name": "Budi Santoso",
        "category": "Dosen",
        "unit": "Sistem Informasi",
        "status": "Aktif",
        "nik": "tidak boleh terbawa",
    }
    routes = {URL.format(nomor="0011223344"): (200, data)}
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen(routes, seen))
    person = directory.lookup(" 0011223344 ")
    assert person == DirectoryPerson(
        "0011223344", "Budi Santoso", "Dosen", "Sistem Informasi", "Aktif"
    )
    assert seen[0].get_header("X-api-key") == "k" * 64
    assert seen[0].get_header("X-api-secret") == "rahasia"


def test_unknown_category_becomes_umum(directory, monkeypatch):
    data = {"member_no": "1", "name": "X", "category": "Alumni", "unit": None, "status": ""}
    routes = {URL.format(nomor="1"): (200, data)}
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen(routes, []))
    person = directory.lookup("1")
    assert (person.category, person.unit) == ("Umum", "")


def test_not_found_and_auth_error(directory, monkeypatch):
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen({}, []))
    assert directory.lookup("999") is None
    routes = {URL.format(nomor="1"): (401, {"detail": "Rahasia API tidak valid"})}
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen(routes, []))
    with pytest.raises(ExtensionError, match="ditolak: Rahasia API tidak valid. Pastikan"):
        directory.lookup("1")
    routes = {URL.format(nomor="1"): (429, None)}
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen(routes, []))
    with pytest.raises(ExtensionError, match="Batas permintaan"):
        directory.lookup("1")


def test_number_is_escaped(directory, monkeypatch):
    seen = []
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen({}, seen))
    directory.lookup("../admin")
    assert seen[0].full_url == "https://directory.example/api/members/..%2Fadmin/"


def test_from_env(monkeypatch):
    for key in ("DIRECTORY_LOOKUP_URL", "DIRECTORY_API_KEY", "DIRECTORY_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert ApiDirectory.from_env() is None
    monkeypatch.setenv("DIRECTORY_LOOKUP_URL", URL)
    monkeypatch.setenv("DIRECTORY_API_KEY", "a")
    monkeypatch.setenv("DIRECTORY_API_SECRET", "b")
    assert ApiDirectory.from_env().lookup_url == URL
    with pytest.raises(ValueError, match="nomor"):
        ApiDirectory("https://directory.example/api/members/", "a", "b")


def json_urlopen(responses, seen):
    """responses: daftar body JSON untuk dikembalikan berurutan."""
    queue = list(responses)

    def urlopen(req, timeout):
        seen.append(req.full_url)
        return FakeResponse(json.dumps(queue.pop(0)).encode())

    return urlopen


def test_search_requires_url_and_min_chars(monkeypatch):
    seen = []
    person = {"member_no": "2301", "name": "Siti", "category": "Mahasiswa", "unit": "TI"}
    body = {"status": True, "data": [person, "bukan-objek"]}
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", json_urlopen([body], seen))
    d = ApiDirectory(URL, "k", "s", search_url="https://directory.example/api/search/")
    assert d.search("si") == []  # kurang dari 3 karakter: tidak memanggil server
    result = d.search("siti a", limit=5)
    assert [p.name for p in result] == ["Siti"]
    assert seen == ["https://directory.example/api/search/?q=siti+a&limit=5"]
    assert ApiDirectory(URL, "k", "s").search("siti") == []  # tanpa search_url


def test_iter_photos_pages_and_skips_invalid(monkeypatch):
    import base64

    seen = []
    ok = base64.b64encode(b"jpeg-1").decode()
    page1 = {
        "status": True,
        "data": [
            {
                "member_no": "2301",
                "name": "A",
                "category": "Mahasiswa",
                "photo": ok,
                "photo_updated_at": "2026-10-01T00:00:00",
            },
            {"member_no": "2302", "name": "B", "photo": "%%%bukan-base64%%%"},
            {"member_no": "2303", "name": "C"},
        ],
        "meta": {"current_page": 1, "last_page": 2},
    }
    page2 = {
        "status": True,
        "data": [{"member_no": "2304", "name": "D", "photo": ok}],
        "meta": {"current_page": 2, "last_page": 2},
    }
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", json_urlopen([page1, page2], seen))
    d = ApiDirectory(URL, "k", "s", faces_url="https://directory.example/api/faces/")
    photos = list(d.iter_photos(updated_since="2026-09-01T00:00:00"))
    assert [(p.person.member_no, p.jpeg) for p in photos] == [
        ("2301", b"jpeg-1"),
        ("2304", b"jpeg-1"),
    ]
    assert photos[0].updated_at == "2026-10-01T00:00:00"
    assert "page=1" in seen[0] and "updated_since=2026-09-01T00%3A00%3A00" in seen[0]
    assert "page=2" in seen[1] and len(seen) == 2


def test_lookup_reads_optional_profile_photo(directory, monkeypatch):
    jpeg = base64.b64encode(b"jpeg-foto").decode()
    routes = {
        URL.format(nomor="1"): (200, {"member_no": "1", "name": "A", "photo": jpeg}),
        URL.format(nomor="2"): (
            200,
            {"member_no": "2", "name": "B", "photo": f"data:image/jpeg;base64,{jpeg}"},
        ),
        URL.format(nomor="3"): (
            200,
            {"member_no": "3", "name": "C", "picture": "https://directory.example/f/3.jpg"},
        ),
        URL.format(nomor="4"): (200, {"member_no": "4", "name": "D"}),
    }
    monkeypatch.setattr(directory_api.urllib.request, "urlopen", fake_urlopen(routes, []))
    assert directory.lookup("1").photo == b"jpeg-foto"
    assert directory.lookup("2").photo == b"jpeg-foto"
    person = directory.lookup("3")
    assert (person.photo, person.photo_url) == (b"", "https://directory.example/f/3.jpg")
    assert directory.fetch_photo(directory.lookup("4")) == b""


def test_fetch_photo_sends_credentials_only_to_directory_host(directory, monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append(req)
        return FakeResponse(b"gambar")

    monkeypatch.setattr(directory_api.urllib.request, "urlopen", urlopen)
    same = DirectoryPerson("1", "A", "Umum", "", "", photo_url="https://directory.example/f/1")
    other = DirectoryPerson("2", "B", "Umum", "", "", photo_url="https://cdn.example/f/2")
    assert directory.fetch_photo(same) == b"gambar"
    assert directory.fetch_photo(other) == b"gambar"
    assert seen[0].get_header("X-api-secret") == "rahasia"
    assert seen[1].get_header("X-api-secret") is None
