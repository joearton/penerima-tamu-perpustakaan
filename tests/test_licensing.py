import base64
import json
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from library_visitor import licensing
from library_visitor.config import Settings
from library_visitor.licensing import (
    LicenseError,
    check_stored_license,
    parse_license,
    save_license,
    validate_license,
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_key(private: Ed25519PrivateKey, **payload) -> str:
    """Format sama dengan license-generator/license_core.py."""
    body = {"v": 1, "id": "ABC123", "licensee": "Universitas Contoh", "issued": "2026-10-01"}
    body.update(payload)
    encoded = _b64(json.dumps(body).encode())
    signature = private.sign(f"PTP1.{encoded}".encode())
    return f"PTP1.{encoded}.{_b64(signature)}"


@pytest.fixture
def private(monkeypatch):
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(licensing, "PUBLIC_KEY", base64.b64encode(raw).decode())
    return key


def test_valid_license_roundtrip(private, tmp_path):
    expires = date.today() + timedelta(days=365)
    key = make_key(private, expires=expires.isoformat())
    lic = validate_license("  " + key[:40] + "\n" + key[40:] + "\n")  # toleran spasi/baris baru
    assert (lic.licensee, lic.id, lic.expires) == ("Universitas Contoh", "ABC123", expires)
    assert lic.days_left() == 365 and "berlaku s/d" in lic.describe()
    save_license(tmp_path, lic)
    assert check_stored_license(tmp_path) == (lic, "")


def test_unlimited_license(private):
    lic = validate_license(make_key(private, expires=None))
    assert lic.expires is None and not lic.is_expired()
    assert "tanpa batas" in lic.describe()


def test_rejects_tampered_or_foreign_keys(private):
    key = make_key(private, expires=None)
    prefix, payload, signature = key.split(".")
    forged = _b64(
        json.dumps({"v": 1, "id": "X", "licensee": "Lain", "issued": "2026-10-01"}).encode()
    )
    with pytest.raises(LicenseError, match="tanda tangan"):
        parse_license(f"{prefix}.{forged}.{signature}")
    with pytest.raises(LicenseError, match="tanda tangan"):
        parse_license(make_key(Ed25519PrivateKey.generate(), expires=None))
    with pytest.raises(LicenseError, match="Format"):
        parse_license("bukan-key")


def test_expired_license_is_rejected_with_reason(private, tmp_path):
    yesterday = date.today() - timedelta(days=1)
    key = make_key(private, expires=yesterday.isoformat())
    assert parse_license(key).is_expired()
    with pytest.raises(LicenseError, match="kedaluwarsa"):
        validate_license(key)
    (tmp_path / "license.key").write_text(key)
    lic, reason = check_stored_license(tmp_path)
    assert lic is None and "kedaluwarsa" in reason
    assert check_stored_license(tmp_path / "kosong") == (None, "")


def test_licensee_is_runtime_only(tmp_path):
    s = Settings(home=tmp_path)
    s.licensee = "Universitas Contoh"
    s.library_address = "Jl. Contoh 1"
    s.save()
    loaded = Settings.load(tmp_path)
    assert loaded.licensee == "" and loaded.library_address == "Jl. Contoh 1"
    assert "licensee" not in s.to_dict()
