import base64
import json
import ssl
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest
from cryptography import x509

from library_visitor.config import Settings
from library_visitor.db import create_session_factory
from library_visitor.face import FaceMatcher, normalize
from library_visitor.services import VisitorService
from library_visitor.web.registration import FaceTools, RegistrationError, WebRegistration
from library_visitor.web.server import (
    LoginGuard,
    WebRegistrationServer,
    is_lan_address,
    web_pin_checker,
)
from library_visitor.web.tls import ensure_certificate


class FakeFace:
    size = 200


class FakeEngine:
    """Gambar gelap = tanpa wajah; selain itu satu wajah, embedding dari warna gambar."""

    def detect(self, frame):
        return [] if frame.mean() < 10 else [FakeFace()]

    def embed(self, frame, face):
        seed = int(frame.reshape(-1, 3).mean(axis=0)[0])
        return normalize(np.random.default_rng(seed).normal(size=128))


def jpeg(value: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((120, 120, 3), value, np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture
def setup(tmp_path):
    settings = Settings(home=tmp_path)
    settings.enroll_samples = 3
    # File, bukan :memory: (database in-memory tidak terlihat dari thread server)
    service = VisitorService(create_session_factory(tmp_path / "db.sqlite"), FaceMatcher(0.4), 30)
    app = WebRegistration(service, settings, tools_factory=lambda s: FaceTools(FakeEngine(), None))
    return settings, service, app


def test_lan_only_addresses():
    for ip in ("127.0.0.1", "192.168.1.20", "10.0.0.5", "172.16.3.4", "::1", "::ffff:192.168.0.2"):
        assert is_lan_address(ip), ip
    for ip in ("8.8.8.8", "203.0.113.9", "bukan-ip"):
        assert not is_lan_address(ip), ip


def test_pin_required_for_web_login(tmp_path):
    s = Settings(home=tmp_path)
    check = web_pin_checker(s)
    assert not check("") and not check("apa saja")  # tanpa PIN, Settings.check_pin = True
    s.set_pin("2468")
    assert check("2468") and not check("1111")


def test_login_guard_locks_after_failures():
    now = [1000.0]
    guard = LoginGuard(lambda pin: pin == "2468", clock=lambda: now[0])
    for _ in range(5):
        with pytest.raises(RegistrationError, match="PIN admin salah"):
            guard.login("192.168.1.9", "0000")
    with pytest.raises(RegistrationError, match="Terlalu banyak") as exc:
        guard.login("192.168.1.9", "2468")  # PIN benar pun ditolak selama terkunci
    assert exc.value.status == 429
    token = guard.login("192.168.1.10", "2468")  # IP lain tidak terdampak
    assert guard.valid(token)
    now[0] += 61
    assert guard.valid(guard.login("192.168.1.9", "2468"))
    now[0] += 9 * 3600
    assert not guard.valid(token)  # sesi kedaluwarsa


def test_certificate_covers_local_ips_and_regenerates(tmp_path):
    cert_path, _ = ensure_certificate(tmp_path, ["192.168.1.20"])
    first = cert_path.read_bytes()
    assert ensure_certificate(tmp_path, ["192.168.1.20"])[0].read_bytes() == first  # dipakai ulang
    ensure_certificate(tmp_path, ["192.168.1.20", "10.0.0.7"])
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert {str(ip) for ip in san.get_values_for_type(x509.IPAddress)} >= {
        "10.0.0.7",
        "192.168.1.20",
    }


def test_register_rejects_bad_photos_and_detects_duplicates(setup):
    settings, service, app = setup
    data = {"member_no": "2301", "name": "Siti", "category": "Mahasiswa", "consent": True}
    with pytest.raises(RegistrationError, match="Persetujuan"):
        app.register({**data, "consent": False}, [jpeg(120)])
    with pytest.raises(RegistrationError, match="Hanya 1 dari 3") as exc:
        app.register(data, [jpeg(120), jpeg(0), b"bukan gambar"])
    assert exc.value.status == 422 and len(exc.value.extra["problems"]) == 2

    result = app.register(data, [jpeg(120)] * 3)
    assert result["face_saved"] and service.get_member_by_no("2301").face_embedding is not None
    assert len(service.matcher) == 1

    other = {**data, "member_no": "2302", "name": "Kembar"}
    with pytest.raises(RegistrationError, match="mirip dengan Siti") as exc:
        app.register(other, [jpeg(120)] * 3)
    assert exc.value.status == 409
    assert app.register({**other, "confirm_duplicate": True}, [jpeg(120)] * 3)["face_saved"]
    assert app.register({**data, "consent": False}, [])["face_saved"] is False  # data saja


def test_server_end_to_end(setup):
    settings, service, app = setup
    settings.set_pin("2468")
    saved = []
    server = WebRegistrationServer(
        app, settings, settings.data_dir / "web", on_saved=lambda: saved.append(1)
    )
    server.start(0, host="127.0.0.1", ips=[])
    base = f"https://127.0.0.1:{server.port}"
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # sertifikat buatan sendiri

    def call(path, body=None, cookie="", headers=None):
        h = {"X-Requested-With": "penerima-tamu", "Content-Type": "application/json"}
        h.update(headers or {})
        if cookie:
            h["Cookie"] = cookie
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, context=context, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    try:
        status, headers, body = call("/")
        assert status == 200 and b"Registrasi Anggota" in body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert call("/api/meta")[0] == 401
        assert call("/api/login", {"pin": "0000"})[0] == 401
        assert call("/api/login", {"pin": "2468"}, headers={"X-Requested-With": ""})[0] == 403
        status, headers, _ = call("/api/login", {"pin": "2468"})
        assert status == 200
        set_cookie = headers["Set-Cookie"]
        assert (
            "HttpOnly" in set_cookie and "Secure" in set_cookie and "SameSite=Strict" in set_cookie
        )
        cookie = set_cookie.split(";")[0]

        status, _, body = call("/api/meta", cookie=cookie)
        assert status == 200 and json.loads(body)["samples"] == 3
        images = ["data:image/jpeg;base64," + base64.b64encode(jpeg(150)).decode()] * 3
        payload = {"member_no": "2401", "name": "Budi", "category": "Dosen", "consent": True}
        status, _, body = call("/api/register", {**payload, "images": images}, cookie=cookie)
        assert status == 200 and json.loads(body)["samples"] == 3
        assert saved == [1]
        status, _, body = call("/api/search?q=bud", cookie=cookie)
        assert json.loads(body)["results"][0]["member_no"] == "2401"
        call("/api/logout", {}, cookie=cookie)
        assert call("/api/meta", cookie=cookie)[0] == 401
    finally:
        server.stop()


def test_server_refuses_to_start_without_pin(setup):
    settings, _, app = setup
    server = WebRegistrationServer(app, settings, settings.data_dir / "web")
    with pytest.raises(RegistrationError, match="PIN admin"):
        server.start(0, host="127.0.0.1", ips=[])
    assert not server.running
