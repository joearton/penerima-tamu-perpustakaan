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


APP_DIR_NAME = "PenerimaTamuPerpustakaan"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def user_data_home() -> Path:
    """Folder data per user untuk versi terinstal (folder instalasi biasanya read-only)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "penerima-tamu-perpustakaan"


def bundled_models_dir() -> Path | None:
    """Model wajah yang ikut dibundel installer (PyInstaller), bila ada."""
    if not is_frozen():
        return None
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    path = bundle / "models"
    return path if path.is_dir() else None


def default_home() -> Path:
    if env := os.environ.get("LV_HOME"):
        return Path(env)
    if is_frozen():
        return user_data_home()
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    home: Path = field(default_factory=default_home, metadata={"persist": False})

    # Umum
    library_name: str = "Perpustakaan"
    # Identitas (nama institusi diambil dari lisensi)
    library_address: str = ""
    library_contact: str = ""  # telepon / email / situs
    library_logo: str = ""  # nama file di folder data, disalin dari file pilihan pengguna
    # Nama institusi dari lisensi aktif; diisi saat runtime, tidak disimpan ke settings.json
    licensee: str = field(default="", metadata={"persist": False})
    kiosk_on_start: bool = False  # langsung buka jendela Mode Kios saat aplikasi dimulai
    # Layar kios menghadap umum: default hanya tampilkan jumlah, bukan nama pengunjung lain
    kiosk_show_names: bool = False
    # Lebar panel kamera/form yang digeser pengguna, per halaman (mis. {"visit": [780, 480]})
    splitter_sizes: dict = field(default_factory=dict)

    # Kamera & pengenalan wajah
    camera_index: int = 0
    # Ambang cosine similarity SFace; nilai rekomendasi OpenCV adalah 0.363
    match_threshold: float = 0.40
    detect_score: float = 0.85
    # Wajah lebih kecil dari ini (piksel) diabaikan karena kualitas embedding buruk
    min_face_size: int = 90
    # Frame berturut-turut yang harus cocok sebelum kunjungan dicatat
    stable_frames: int = 5
    # Beberapa wajah: catat semua anggota yang dikenali dalam satu frame (bukan hanya terdekat)
    multi_face: bool = True
    max_faces: int = 4

    # Tebakan identitas saat registrasi dari galeri foto direktori
    photo_suggest_enabled: bool = True
    photo_suggest_count: int = 3
    photo_suggest_min_score: float = 0.30
    gallery_auto_sync: bool = True  # sinkron inkremental otomatis sekali sehari
    # Filter galeri (kosong = tanpa filter); dipisahkan koma
    gallery_categories: str = ""  # mis. "Mahasiswa"
    gallery_prefixes: str = ""  # awalan nomor induk, mis. "23,24,25,26"
    gallery_status: str = ""  # status wajib, mis. "Aktif"
    enroll_samples: int = 5
    # Anti-spoofing (MiniFASNet): tolak wajah dari foto/layar
    antispoof_enabled: bool = True
    antispoof_threshold: float = 0.80  # skor "wajah asli" minimal (0-1)

    # Kunjungan: anggota yang sama tidak dicatat ulang dalam rentang ini
    visit_cooldown_minutes: int = 30
    # Pengunjung tak dikenal dihitung "Anonim" (embedding hanya di memori selama jeda catat ulang)
    anonymous_enabled: bool = True
    anonymous_min_frames: int = 10  # lebih ketat dari anggota agar orang lewat tidak terhitung
    anonymous_same_threshold: float = 0.40  # kemiripan untuk dianggap orang yang sama

    # Sapaan. Placeholder: {salam} {nama} {nama_depan} {kategori} {perpustakaan}
    greeting_template: str = "{salam}, {nama_depan}! Selamat datang di {perpustakaan}."
    repeat_template: str = "Halo {nama_depan}, kunjungan Anda hari ini sudah tercatat."
    guest_template: str = "{salam}, {nama}! Selamat datang di {perpustakaan}."
    anonymous_template: str = "{salam}! Selamat datang di {perpustakaan}."
    banner_seconds: int = 5

    # Suara
    sound_enabled: bool = True
    sound_file: str = ""  # kosong = bunyi bawaan
    tts_enabled: bool = True
    tts_lang: str = "id"
    tts_slow: bool = False
    speak_repeat: bool = False  # ucapkan juga sapaan "sudah tercatat"
    volume: int = 80

    # Backup otomatis harian
    auto_backup_enabled: bool = True
    backup_dir: str = ""  # kosong = data/backups
    backup_keep: int = 14  # jumlah backup harian yang disimpan

    # Keamanan: tab admin dikunci bila PIN diisi dan/atau admin login eksternal diatur
    admin_pin_hash: str = ""
    admin_usernames: str = ""  # username dari login eksternal, pisahkan dengan koma
    admin_group: str = ""  # atau semua anggota grup ini

    # Registrasi via web (HTTPS, khusus LAN); butuh PIN admin untuk login
    web_enabled: bool = False
    web_port: int = 8443

    @property
    def models_dir(self) -> Path:
        return bundled_models_dir() or self.home / "models"

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
    def logo_path(self) -> Path | None:
        if not self.library_logo:
            return None
        path = self.data_dir / self.library_logo
        return path if path.is_file() else None

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
