"""Ekspor laporan kunjungan ke Excel."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

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


def export_excel(service: VisitorService, start: date, end: date, path: Path) -> int:
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
        df.to_excel(writer, sheet_name="Detail", index=False)
        daily.to_excel(writer, sheet_name="Rekap Harian")
    return len(df)
