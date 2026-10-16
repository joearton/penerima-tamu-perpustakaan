"""Penyusunan teks sapaan dari template."""

from __future__ import annotations

from datetime import datetime

PLACEHOLDERS = {
    "{salam}": "Selamat pagi/siang/sore/malam sesuai jam",
    "{nama}": "nama lengkap",
    "{nama_depan}": "kata pertama dari nama",
    "{kategori}": "kategori anggota",
    "{lokasi}": "nama lokasi/instansi yang dikunjungi",
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


def join_names(names: list[str]) -> str:
    """["A"] -> "A"; ["A", "B"] -> "A dan B"; ["A", "B", "C"] -> "A, B, dan C"."""
    if len(names) <= 2:
        return " dan ".join(names)
    return ", ".join(names[:-1]) + ", dan " + names[-1]


def _first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def render(
    template: str,
    name: str,
    category: str = "",
    library: str = "",
    now: datetime | None = None,
) -> str:
    return render_group(template, [(name, category)], library, now)


def render_group(
    template: str,
    people: list[tuple[str, str]],
    library: str = "",
    now: datetime | None = None,
) -> str:
    """Sapaan untuk satu atau beberapa orang sekaligus; `people` berisi (nama, kategori)."""
    categories = {category for _, category in people}
    values = _Keep(
        salam=salutation(now),
        nama=join_names([name for name, _ in people]),
        nama_depan=join_names([_first_name(name) for name, _ in people]),
        kategori=categories.pop() if len(categories) == 1 else "",
        lokasi=library,
        perpustakaan=library,  # nama lama, tetap didukung untuk template lama
    )
    try:
        return template.format_map(values)
    except (ValueError, IndexError):  # kurung kurawal tidak berpasangan, dll.
        return template
