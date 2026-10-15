"""Pengaturan aplikasi, disimpan di data/settings.json dan bisa diubah dari tab Pengaturan."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


def default_home() -> Path:
    if env := os.environ.get("LV_HOME"):
        return Path(env)
    # Saat dibundel PyInstaller, simpan data di samping file executable
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    home: Path = field(default_factory=default_home, metadata={"persist": False})

    # Umum
    library_name: str = "Perpustakaan"

    # Kamera & pengenalan wajah
    camera_index: int = 0
    # Ambang cosine similarity SFace; nilai rekomendasi OpenCV adalah 0.363
    match_threshold: float = 0.40
    detect_score: float = 0.85
    # Wajah lebih kecil dari ini (piksel) diabaikan karena kualitas embedding buruk
    min_face_size: int = 90
    # Frame berturut-turut yang harus cocok sebelum kunjungan dicatat
    stable_frames: int = 5
    enroll_samples: int = 5

    # Kunjungan: anggota yang sama tidak dicatat ulang dalam rentang ini
    visit_cooldown_minutes: int = 30

    # Sapaan. Placeholder: {salam} {nama} {nama_depan} {kategori} {perpustakaan}
    greeting_template: str = "{salam}, {nama_depan}! Selamat datang di {perpustakaan}."
    repeat_template: str = "Halo {nama_depan}, kunjungan Anda hari ini sudah tercatat."
    guest_template: str = "{salam}, {nama}! Selamat datang di {perpustakaan}."
    banner_seconds: int = 5

    # Suara
    sound_enabled: bool = True
    sound_file: str = ""  # kosong = bunyi bawaan
    tts_enabled: bool = True
    tts_lang: str = "id"
    tts_slow: bool = False
    speak_repeat: bool = False  # ucapkan juga sapaan "sudah tercatat"
    volume: int = 80

    # Keamanan: tab admin dikunci bila PIN diisi dan/atau admin login eksternal diatur
    admin_pin_hash: str = ""
    admin_usernames: str = ""  # username dari login eksternal, pisahkan dengan koma
    admin_group: str = ""  # atau semua anggota grup ini

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "library_visitor.db"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def tts_cache_dir(self) -> Path:
        return self.data_dir / "tts_cache"

    @classmethod
    def load(cls, home: Path | None = None) -> Settings:
        settings = cls(home=home) if home else cls()
        path = settings.settings_path
        if path.exists():
            try:
                settings.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                log.warning("settings.json tidak bisa dibaca, memakai default: %s", exc)
        return settings

    def update(self, values: dict) -> None:
        """Set nilai yang dikenal dengan konversi tipe; kunci yang tidak dikenal diabaikan."""
        for f in fields(self):
            if f.name in values and f.metadata.get("persist", True):
                default = getattr(self, f.name)
                setattr(self, f.name, type(default)(values[f.name]))

    def to_dict(self) -> dict:
        data = asdict(self)
        return {f.name: data[f.name] for f in fields(self) if f.metadata.get("persist", True)}

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.settings_path)

    # ---------- PIN admin ----------

    @property
    def pin_enabled(self) -> bool:
        return bool(self.admin_pin_hash)

    def set_pin(self, pin: str) -> None:
        salt = secrets.token_hex(8)
        self.admin_pin_hash = f"{salt}${_hash_pin(salt, pin)}" if pin else ""

    def check_pin(self, pin: str) -> bool:
        if not self.admin_pin_hash:
            return True
        salt, digest = self.admin_pin_hash.split("$", 1)
        return secrets.compare_digest(_hash_pin(salt, pin), digest)


def _hash_pin(salt: str, pin: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()
