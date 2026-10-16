"""Ekspor laporan kunjungan ke Excel."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from library_visitor.config import Settings
from library_visitor.services import VisitorService, visit_category, visitor_name

METHOD_LABELS = {"face": "Wajah", "manual": "Manual", "guest": "Tamu", "anonymous": "Anonim"}
REPORT_COLUMNS = ("Waktu", "No. Anggota", "Nama", "Kategori", "Prodi/Unit", "Metode", "Keperluan")


def visits_dataframe(service: VisitorService, start: date, end: date) -> pd.DataFrame:
    rows = [
        {
            "Waktu": v.visited_at,
            "No. Anggota": v.member.member_no if v.member else "",
            "Nama": visitor_name(v),
            "Kategori": visit_category(v),
            "Prodi/Unit": (v.member.unit or "") if v.member else "",
            "Metode": METHOD_LABELS.get(v.method, v.method),
            "Keperluan": v.purpose or "",
        }
        for v in service.visits_between(start, end)
    ]
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def identity_rows(settings: Settings, start: date, end: date) -> pd.DataFrame:
    """Sheet "Info": identitas perpustakaan dan periode laporan."""
    rows = [
        ("Perpustakaan", settings.library_name),
        ("Institusi", settings.licensee),
        ("Alamat", settings.library_address),
        ("Kontak", settings.library_contact),
        ("Periode", f"{start:%d-%m-%Y} s/d {end:%d-%m-%Y}"),
        ("Dibuat", f"{datetime.now():%d-%m-%Y %H:%M}"),
    ]
    return pd.DataFrame([r for r in rows if r[1]], columns=["Keterangan", "Isi"])


def export_excel(
    service: VisitorService, start: date, end: date, path: Path, settings: Settings | None = None
) -> int:
    df = visits_dataframe(service, start, end).sort_values("Waktu")
    daily = (
        df.assign(Tanggal=df["Waktu"].dt.date).pivot_table(
            index="Tanggal", columns="Kategori", values="Nama", aggfunc="count", fill_value=0
        )
        if not df.empty
        else pd.DataFrame()
    )
    if not daily.empty:
        daily["Total"] = daily.sum(axis=1)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if settings is not None:
            info = identity_rows(settings, start, end)
            info.to_excel(writer, sheet_name="Info", index=False)
            sheet = writer.sheets["Info"]
            sheet.column_dimensions["A"].width = 16
            sheet.column_dimensions["B"].width = max(40, int(info["Isi"].str.len().max()) + 2)
        df.to_excel(writer, sheet_name="Detail", index=False)
        daily.to_excel(writer, sheet_name="Rekap Harian")
    return len(df)
