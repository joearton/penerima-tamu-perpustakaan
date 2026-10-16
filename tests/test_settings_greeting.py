from datetime import datetime

from library_visitor import greeting
from library_visitor.config import Settings


def test_settings_roundtrip_and_pin(tmp_path):
    s = Settings.load(tmp_path)
    assert s.library_name == "Perpustakaan"
    s.update({"library_name": "Perpus UIN", "volume": "55", "unknown_key": 1})
    s.set_pin("1234")
    s.save()
    loaded = Settings.load(tmp_path)
    assert loaded.library_name == "Perpus UIN" and loaded.volume == 55
    assert loaded.check_pin("1234") and not loaded.check_pin("0000")
    assert "home" not in loaded.to_dict()
    loaded.set_pin("")
    assert not loaded.pin_enabled and loaded.check_pin("apa saja")


def test_corrupt_settings_falls_back_to_default(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.json").write_text("{rusak")
    assert Settings.load(tmp_path).camera_index == 0


def test_greeting_render():
    morning = datetime(2026, 1, 1, 8, 0)
    night = datetime(2026, 1, 1, 20, 0)
    text = greeting.render(
        "{salam}, {nama_depan}! {perpustakaan}", "Siti Aminah", "", "Perpus", morning
    )
    assert text == "Selamat pagi, Siti! Perpus"
    assert greeting.render("{salam}", "X", now=night) == "Selamat malam"
    # Placeholder tak dikenal dan kurung tak berpasangan tidak membuat crash
    assert greeting.render("Hai {nama} {lain}", "Ani") == "Hai Ani {lain}"
    assert greeting.render("Hai {nama", "Ani") == "Hai {nama"


def test_render_group_joins_names():
    morning = datetime(2026, 1, 1, 8, 0)
    people = [("Siti Aminah", "Mahasiswa"), ("Budi Santoso", "Dosen"), ("Rina", "Mahasiswa")]
    text = greeting.render_group("{salam}, {nama_depan}! ({kategori})", people, "P", morning)
    assert text == "Selamat pagi, Siti, Budi, dan Rina! ()"
    two = greeting.render_group("{nama}", people[:2])
    assert two == "Siti Aminah dan Budi Santoso"
    same_category = greeting.render_group("{kategori}", [people[0], people[2]])
    assert same_category == "Mahasiswa"
