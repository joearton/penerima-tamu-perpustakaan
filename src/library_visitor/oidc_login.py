"""Login admin lewat penyedia OAuth2/OpenID Connect: authorization code + PKCE (S256)
dengan redirect loopback.

Klien bertipe public (tanpa secret). Token hanya dipakai sekali untuk membaca endpoint
userinfo lalu dibuang; aplikasi tidak menyimpan token apa pun.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

from library_visitor.directory_api import USER_AGENT
from library_visitor.extensions import AdminUser, ExtensionError

DEFAULT_REDIRECT = "http://127.0.0.1:8765/callback"
DEFAULT_SCOPE = "openid profile email"

_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>Library Visitor</title>
<body style="font-family:sans-serif;text-align:center;padding-top:15vh">
<h2>{title}</h2><p>{text}</p></body>"""


class OAuthError(ExtensionError):
    pass


@dataclass(frozen=True)
class OAuthConfig:
    authorize_url: str
    token_url: str
    userinfo_url: str
    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT
    scope: str = DEFAULT_SCOPE

    @classmethod
    def from_env(cls) -> OAuthConfig | None:
        """None bila salah satu variabel OAUTH_* wajib belum diisi."""
        env = {
            k: os.environ.get(f"OAUTH_{k}", "").strip()
            for k in ("AUTHORIZE_URL", "TOKEN_URL", "USERINFO_URL", "CLIENT_ID")
        }
        if not all(env.values()):
            return None
        return cls(
            env["AUTHORIZE_URL"],
            env["TOKEN_URL"],
            env["USERINFO_URL"],
            env["CLIENT_ID"],
            os.environ.get("OAUTH_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT,
            os.environ.get("OAUTH_SCOPE", "").strip() or DEFAULT_SCOPE,
        )


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def user_from_userinfo(info: dict) -> AdminUser:
    groups = info.get("groups") or []
    return AdminUser(
        username=str(info.get("preferred_username") or info.get("sub") or ""),
        name=str(info.get("name") or ""),
        groups=tuple(str(g) for g in groups),
    )


class PKCELogin:
    """Satu kali proses login. `run()` memblokir, jadi panggil dari thread latar."""

    def __init__(self, config: OAuthConfig, timeout: float = 180) -> None:
        self._config = config
        self._timeout = timeout
        self._cancelled = threading.Event()
        self._verifier, self._challenge = pkce_pair()
        self._state = secrets.token_urlsafe(24)
        parsed = urllib.parse.urlparse(config.redirect_uri)
        if parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
            raise OAuthError("Redirect URI harus loopback dengan port, mis. " + DEFAULT_REDIRECT)
        self._host, self._port, self._path = parsed.hostname, parsed.port, parsed.path

    def authorize_url(self) -> str:
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "scope": self._config.scope,
                "state": self._state,
                "code_challenge": self._challenge,
                "code_challenge_method": "S256",
            }
        )
        sep = "&" if "?" in self._config.authorize_url else "?"
        return f"{self._config.authorize_url}{sep}{query}"

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self, open_browser: Callable[[str], object]) -> AdminUser:
        code = self._wait_for_code(open_browser)
        token = self._exchange(code)
        return user_from_userinfo(self._request(self._config.userinfo_url, token=token))

    # ---------- langkah-langkah ----------

    def _wait_for_code(self, open_browser: Callable[[str], object]) -> str:
        result: dict[str, str] = {}
        expected_path, expected_state = self._path, self._state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (nama dari http.server)
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != expected_path:
                    self.send_error(404)
                    return
                params = dict(urllib.parse.parse_qsl(parsed.query))
                if params.get("state") != expected_state:
                    result["error"] = "state tidak cocok (kemungkinan permintaan palsu)"
                elif "error" in params:
                    result["error"] = params.get("error_description") or params["error"]
                elif "code" in params:
                    result["code"] = params["code"]
                else:
                    result["error"] = "callback tanpa kode otorisasi"
                ok = "code" in result
                page = _DONE_PAGE.format(
                    title="Login berhasil" if ok else "Login gagal",
                    text="Silakan kembali ke aplikasi." if ok else result.get("error", ""),
                )
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page.encode())

            def log_message(self, *_args):  # jangan tulis query (berisi kode) ke stderr
                pass

        try:
            server = HTTPServer((self._host, self._port), Handler)
        except OSError as exc:
            raise OAuthError(f"Port {self._port} sedang dipakai aplikasi lain: {exc}") from None
        server.timeout = 0.5
        deadline = time.monotonic() + self._timeout
        try:
            open_browser(self.authorize_url())
            while not result:
                if self._cancelled.is_set():
                    raise OAuthError("Login dibatalkan")
                if time.monotonic() > deadline:
                    raise OAuthError("Waktu login habis")
                server.handle_request()
        finally:
            server.server_close()
        if "error" in result:
            raise OAuthError(f"Login gagal: {result['error']}")
        return result["code"]

    def _exchange(self, code: str) -> str:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config.redirect_uri,
                "client_id": self._config.client_id,
                "code_verifier": self._verifier,
            }
        ).encode()
        data = self._request(self._config.token_url, body=body)
        if not data.get("access_token"):
            raise OAuthError("Server login tidak mengembalikan access token")
        return data["access_token"]

    def _request(self, url: str, body: bytes | None = None, token: str | None = None) -> dict:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            raise OAuthError(f"Server login menolak permintaan (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise OAuthError(f"Tidak bisa terhubung ke server login: {exc}") from None
        except ValueError:
            raise OAuthError("Respons server login bukan JSON yang valid") from None


class OAuthLoginProvider:
    """AdminLoginProvider berbasis OAuth2/OIDC; label tombol bisa diatur lewat OAUTH_LABEL."""

    def __init__(self, config: OAuthConfig, label: str = "Masuk dengan akun institusi") -> None:
        self.config = config
        self.label = label

    @classmethod
    def from_env(cls) -> OAuthLoginProvider | None:
        config = OAuthConfig.from_env()
        if config is None:
            return None
        return cls(
            config, os.environ.get("OAUTH_LABEL", "").strip() or "Masuk dengan akun institusi"
        )

    def start(self) -> PKCELogin:
        return PKCELogin(self.config)
