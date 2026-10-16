"""Sertifikat HTTPS buatan sendiri untuk server registrasi di LAN.

Browser hanya mengizinkan kamera (getUserMedia) di halaman aman, jadi server wajib HTTPS.
Sertifikat dibuat otomatis untuk semua alamat IP lokal PC ini; perangkat yang membuka laman
akan melihat peringatan sertifikat sekali dan perlu memilih "lanjutkan".
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

log = logging.getLogger(__name__)

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"
VALID_DAYS = 825  # batas maksimal yang masih diterima Safari/iOS
RENEW_BEFORE = timedelta(days=30)


def local_ipv4_addresses() -> list[str]:
    """Alamat IPv4 PC ini di jaringan lokal (tanpa loopback), alamat utama lebih dulu."""
    found: list[str] = []
    try:  # alamat yang dipakai untuk rute keluar; tidak ada paket yang benar-benar dikirim
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    result = []
    for addr in found:
        ip = ipaddress.ip_address(addr)
        if not ip.is_loopback and not ip.is_link_local and addr not in result:
            result.append(addr)
    return result


def _covers(cert: x509.Certificate, ips: list[str]) -> bool:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    listed = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return set(ips) <= listed


def ensure_certificate(directory: Path, ips: list[str] | None = None) -> tuple[Path, Path]:
    """(cert, key); dibuat ulang bila belum ada, hampir kedaluwarsa, atau IP berubah."""
    ips = local_ipv4_addresses() if ips is None else ips
    cert_path, key_path = directory / CERT_FILE, directory / KEY_FILE
    if cert_path.exists() and key_path.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            fresh = cert.not_valid_after_utc - datetime.now(UTC) > RENEW_BEFORE
            if fresh and _covers(cert, ips):
                return cert_path, key_path
        except ValueError:
            pass
    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    hostname = socket.gethostname() or "penerima-tamu"
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Penerima Tamu ({hostname})")])
    alt_names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(hostname),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Sertifikat HTTPS registrasi web dibuat untuk %s", ", ".join(ips) or "localhost")
    return cert_path, key_path
