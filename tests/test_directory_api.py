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
