"""Server HTTPS registrasi anggota via web, khusus jaringan lokal (LAN).

- Hanya menerima koneksi dari alamat privat/loopback (jaringan lokal).
- Login dengan PIN admin; sesi via cookie HttpOnly + Secure + SameSite=Strict.
- Percobaan PIN dibatasi per alamat IP.
- Berjalan di thread terpisah; operasi database aman dipanggil dari thread ini.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import logging
import secrets
import ssl
import sys
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from library_visitor.config import Settings
from library_visitor.web.registration import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    RegistrationError,
    WebRegistration,
)

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
SESSION_COOKIE = "pt_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY = MAX_IMAGES * MAX_IMAGE_BYTES * 4 // 3 + 64 * 1024
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
}


# Jaringan lokal saja (bukan `is_private`, yang juga mencakup rentang dokumentasi dsb.)
LAN_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
]


def is_lan_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in LAN_NETWORKS)


class LoginGuard:
    """Sesi login dan pembatas percobaan PIN per IP."""

    def __init__(self, check_pin: Callable[[str], bool], clock=time.monotonic) -> None:
        self._check_pin = check_pin
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def login(self, ip: str, pin: str) -> str:
        now = self._clock()
        with self._lock:
            count, locked_until = self._failures.get(ip, (0, 0.0))
            if locked_until > now:
                wait = int(locked_until - now) + 1
                raise RegistrationError(f"Terlalu banyak percobaan. Coba lagi {wait} detik.", 429)
        if not self._check_pin(pin):
            with self._lock:
                count += 1
                lock = now + LOGIN_LOCK_SECONDS if count >= LOGIN_MAX_FAILURES else 0.0
                self._failures[ip] = (0 if lock else count, lock)
            log.warning("Registrasi web: PIN salah dari %s", ip)
            raise RegistrationError("PIN admin salah", 401)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._failures.pop(ip, None)
            self._sessions[token] = now + SESSION_SECONDS
        log.info("Registrasi web: login dari %s", ip)
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        now = self._clock()
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None or expiry < now:
                self._sessions.pop(token, None)
                return False
            return True

    def logout(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"
    server_version = "PenerimaTamu"
    sys_version = ""
    timeout = 60  # detik; koneksi menggantung tidak menahan thread selamanya

    # ---------- util ----------

    def log_message(self, fmt: str, *args) -> None:  # jangan cetak ke stderr
        log.debug("web %s - %s", self.client_address[0], fmt % args)

    def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: dict, headers: dict | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, exc: RegistrationError) -> None:
        self._json(exc.status, {"error": str(exc), **exc.extra})

    def _token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _authorized(self) -> bool:
        if self.server.guard.valid(self._token()):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "Silakan login dengan PIN admin"})
        return False

    def _body(self) -> dict:
        # Cegah CSRF: wajib JSON + header khusus (tidak bisa dikirim form lintas situs)
        if self.headers.get("X-Requested-With") != "penerima-tamu":
            raise RegistrationError("Permintaan ditolak", 403)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise RegistrationError("Format permintaan harus JSON", 415)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise RegistrationError("Data terlalu besar", 413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise RegistrationError("JSON tidak valid") from None
        if not isinstance(data, dict):
            raise RegistrationError("JSON tidak valid")
        return data

    def _allowed_client(self) -> bool:
        if is_lan_address(self.client_address[0]):
            return True
        log.warning("Registrasi web: akses ditolak dari %s (bukan LAN)", self.client_address[0])
        self._json(HTTPStatus.FORBIDDEN, {"error": "Hanya bisa diakses dari jaringan lokal"})
        return False

    # ---------- routing ----------

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed_client():
            return
        url = urlsplit(self.path)
        if url.path in STATIC_FILES:
            name, content_type = STATIC_FILES[url.path]
            self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), content_type)
            return
        query = parse_qs(url.query)
        app = self.server.app
        try:
            if url.path == "/api/session":
                self._json(HTTPStatus.OK, {"authenticated": self.server.guard.valid(self._token())})
            elif url.path == "/api/meta":
                if self._authorized():
                    self._json(HTTPStatus.OK, app.meta())
            elif url.path == "/api/search":
                if self._authorized():
                    results = app.search(query.get("q", [""])[0])
                    self._json(HTTPStatus.OK, {"results": results})
            elif url.path == "/api/lookup":
                if self._authorized():
                    self._json(HTTPStatus.OK, app.lookup(query.get("no", [""])[0]))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Tidak ditemukan"})
        except RegistrationError as exc:
            self._error(exc)
        except Exception:
            log.exception("Registrasi web: galat GET %s", url.path)
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Galat di server"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed_client():
            return
        path = urlsplit(self.path).path
        ip = self.client_address[0]
        try:
            data = self._body()
            if path == "/api/login":
                token = self.server.guard.login(ip, str(data.get("pin", "")))
                cookie = (
                    f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_SECONDS}; "
                    "HttpOnly; Secure; SameSite=Strict"
                )
                self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": cookie})
            elif path == "/api/logout":
                self.server.guard.logout(self._token())
                cookie = f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
                self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": cookie})
            elif path == "/api/register":
                if not self._authorized():
                    return
                images = _decode_images(data.get("images") or [])
                result = self.server.app.register(data, images)
                log.info(
                    "Registrasi web dari %s: %s (%s), wajah %s",
                    ip,
                    result["name"],
                    result["member_no"],
                    "disimpan" if result["face_saved"] else "tidak diubah",
                )
                self.server.on_saved()
                self._json(HTTPStatus.OK, result)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Tidak ditemukan"})
        except RegistrationError as exc:
            self._error(exc)
        except Exception:
            log.exception("Registrasi web: galat POST %s", path)
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Galat di server"})


def _decode_images(items: list) -> list[bytes]:
    if not isinstance(items, list) or len(items) > MAX_IMAGES:
        raise RegistrationError(f"Jumlah foto tidak valid (maksimal {MAX_IMAGES})")
    images = []
    for item in items:
        text = str(item)
        if text.startswith("data:"):
            text = text.partition(",")[2]
        try:
            data = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raise RegistrationError("Foto tidak valid") from None
        if len(data) > MAX_IMAGE_BYTES:
            raise RegistrationError("Ukuran foto terlalu besar")
        images.append(data)
    return images


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # cegah dua instance diam-diam berbagi port di Windows

    def __init__(self, address, app: WebRegistration, guard: LoginGuard, on_saved) -> None:
        super().__init__(address, _Handler)
        self.app = app
        self.guard = guard
        self.on_saved = on_saved

    def handle_error(self, request, client_address) -> None:
        # Browser yang belum menerima sertifikat buatan sendiri memutus handshake TLS; ini wajar
        exc = sys.exc_info()[1]
        if isinstance(exc, (ssl.SSLError, ConnectionError, TimeoutError)):
            log.debug("Registrasi web: koneksi %s terputus: %s", client_address[0], exc)
        else:
            log.exception("Registrasi web: galat koneksi dari %s", client_address[0])


def web_pin_checker(settings: Settings) -> Callable[[str], bool]:
    """PIN wajib sudah diatur: tanpa PIN, Settings.check_pin menerima apa saja."""
    return lambda pin: settings.pin_enabled and bool(pin) and settings.check_pin(pin)


class WebRegistrationServer:
    """Pembungkus server: start/stop dari thread UI."""

    def __init__(
        self,
        app: WebRegistration,
        settings: Settings,
        cert_dir: Path,
        on_saved: Callable[[], None] = lambda: None,
    ) -> None:
        self._app = app
        self._settings = settings
        self._cert_dir = cert_dir
        self._on_saved = on_saved
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int, host: str = "0.0.0.0", ips: list[str] | None = None) -> None:
        from library_visitor.web.tls import ensure_certificate

        self.stop()
        if not self._settings.pin_enabled:
            raise RegistrationError("Atur PIN admin dulu sebelum mengaktifkan registrasi web")
        cert, key = ensure_certificate(self._cert_dir, ips)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        guard = LoginGuard(web_pin_checker(self._settings))
        server = _Server((host, port), self._app, guard, self._on_saved)
        # Handshake TLS di thread koneksi masing-masing, bukan di loop accept
        server.socket = context.wrap_socket(
            server.socket, server_side=True, do_handshake_on_connect=False
        )
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(
            target=server.serve_forever, name="web-registrasi", daemon=True
        )
        self._thread.start()
        log.info("Registrasi web aktif di port %d", self.port)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        log.info("Registrasi web dihentikan")
