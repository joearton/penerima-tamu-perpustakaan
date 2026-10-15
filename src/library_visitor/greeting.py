"""Penyusunan teks sapaan dari template."""

from __future__ import annotations

from datetime import datetime

PLACEHOLDERS = {
    "{salam}": "Selamat pagi/siang/sore/malam sesuai jam",
    "{nama}": "nama lengkap",
    "{nama_depan}": "kata pertama dari nama",
    "{kategori}": "kategori anggota",
    "{perpustakaan}": "nama perpustakaan",
}


class _Keep(dict):
    """Placeholder yang tidak dikenal dibiarkan apa adanya, bukan error."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def salutation(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if 4 <= hour < 11:
        return "Selamat pagi"
    if 11 <= hour < 15:
        return "Selamat siang"
    if 15 <= hour < 18:
        return "Selamat sore"
    return "Selamat malam"


def render(
    template: str,
    name: str,
    category: str = "",
    library: str = "",
    now: datetime | None = None,
) -> str:
    values = _Keep(
        salam=salutation(now),
        nama=name,
        nama_depan=name.split()[0] if name.split() else name,
        kategori=category,
        perpustakaan=library,
    )
    try:
        return template.format_map(values)
    except (ValueError, IndexError):  # kurung kurawal tidak berpasangan, dll.
        return template
