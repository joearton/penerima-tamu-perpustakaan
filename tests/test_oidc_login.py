import json
import socket
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from library_visitor.extensions import AdminUser, is_admin, parse_admin_usernames
from library_visitor.oidc_login import OAuthConfig, OAuthError, OAuthLoginProvider, PKCELogin


def make_config(base: str, redirect: str) -> OAuthConfig:
    return OAuthConfig(
        f"{base}/o/authorize/", f"{base}/o/token/", f"{base}/userinfo/", "client-abc", redirect
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_idp():
    """Server OAuth2/OIDC tiruan: authorize redirect, token memeriksa PKCE, lalu userinfo."""
    state = {"challenge": None, "token_form": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, data):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/o/authorize/":
                state["challenge"] = q["code_challenge"]
                assert q["code_challenge_method"] == "S256" and q["scope"] == "openid profile email"
                target = f"{q['redirect_uri']}?code=KODE123&state={q['state']}"
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
            elif url.path == "/userinfo/":
                assert self.headers["Authorization"] == "Bearer TOKEN"
                self._json(
                    200,
                    {
                        "preferred_username": "0011223344",
                        "name": "Budi Santoso",
                        "email": "budi@example.ac.id",
                        "groups": ["Pustakawan"],
                    },
                )
            else:
                self._json(404, {})

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            state["token_form"] = dict(urllib.parse.parse_qsl(body))
            self._json(200, {"access_token": "TOKEN", "token_type": "Bearer"})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()


def browser():
    """Simulasi browser: buka URL authorize di thread lain dan ikuti redirect."""

    def open_url(url):
        threading.Thread(
            target=lambda: urllib.request.urlopen(url, timeout=5).read(), daemon=True
        ).start()

    return open_url


def test_full_pkce_flow(fake_idp):
    base, state = fake_idp
    config = make_config(base, f"http://127.0.0.1:{free_port()}/callback")
    login = PKCELogin(config, timeout=10)
    user = login.run(browser())
    assert user == AdminUser("0011223344", "Budi Santoso", ("Pustakawan",))
    form = state["token_form"]
    assert form["code"] == "KODE123" and form["client_id"] == "client-abc"
    assert "client_secret" not in form
    # verifier yang dikirim ke /o/token/ harus cocok dengan challenge di /o/authorize/
    import base64
    import hashlib

    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == state["challenge"]


def test_state_mismatch_rejected():
    port = free_port()
    login = PKCELogin(make_config("http://x", f"http://127.0.0.1:{port}/callback"), timeout=5)

    def attacker(_url):
        cb = f"http://127.0.0.1:{port}/callback?code=EVIL&state=salah"
        threading.Thread(target=lambda: _quiet_get(cb), daemon=True).start()

    with pytest.raises(OAuthError, match="state"):
        login.run(attacker)


def _quiet_get(url):
    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


def test_cancel_and_redirect_validation():
    with pytest.raises(OAuthError, match="loopback"):
        PKCELogin(make_config("http://x", "https://evil.example/callback"))
    login = PKCELogin(make_config("http://x", f"http://127.0.0.1:{free_port()}/callback"))
    login.cancel()
    with pytest.raises(OAuthError, match="dibatalkan"):
        login.run(lambda url: None)


def test_admin_rules():
    user = AdminUser("Budi.S", "Budi", ("Pustakawan",))
    assert is_admin(user, parse_admin_usernames("x, budi.s"), "")
    assert is_admin(user, set(), "pustakawan")
    assert not is_admin(user, {"lain"}, "")
    assert not is_admin(user, set(), "")


def test_provider_from_env(monkeypatch):
    for key in ("AUTHORIZE_URL", "TOKEN_URL", "USERINFO_URL", "CLIENT_ID"):
        monkeypatch.delenv(f"OAUTH_{key}", raising=False)
    assert OAuthLoginProvider.from_env() is None
    monkeypatch.setenv("OAUTH_AUTHORIZE_URL", "https://idp.example/authorize?x=1")
    monkeypatch.setenv("OAUTH_TOKEN_URL", "https://idp.example/token")
    monkeypatch.setenv("OAUTH_USERINFO_URL", "https://idp.example/userinfo")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "abc")
    monkeypatch.setenv("OAUTH_LABEL", "Masuk dengan akun kantor")
    provider = OAuthLoginProvider.from_env()
    assert provider.label == "Masuk dengan akun kantor"
    assert provider.config.redirect_uri == "http://127.0.0.1:8765/callback"
    url = provider.start().authorize_url()
    assert url.startswith("https://idp.example/authorize?x=1&response_type=code")
