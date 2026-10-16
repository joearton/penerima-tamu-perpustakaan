"""Membuat ikon aplikasi (icon.png 256px dan icon.ico) dengan Qt; jalankan bila ikon diubah."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen

OUT = Path(__file__).resolve().parent


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.setBrush(QBrush(QColor("#1e8449")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)
    # Buku terbuka
    p.setBrush(QBrush(QColor("white")))
    p.drawRoundedRect(QRectF(44 * s, 150 * s, 80 * s, 56 * s), 6 * s, 6 * s)
    p.drawRoundedRect(QRectF(132 * s, 150 * s, 80 * s, 56 * s), 6 * s, 6 * s)
    # Bingkai wajah (sudut pemindai) di atas buku
    pen = QPen(QColor("white"), 12 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(100 * s, 52 * s, 56 * s, 64 * s))
    for x, y, dx, dy in ((70, 40, 1, 1), (186, 40, -1, 1), (70, 128, 1, -1), (186, 128, -1, -1)):
        p.drawLine(int(x * s), int(y * s), int((x + 22 * dx) * s), int(y * s))
        p.drawLine(int(x * s), int(y * s), int(x * s), int((y + 22 * dy) * s))
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    draw(256).save(str(OUT / "icon.png"))
    draw(256).save(str(OUT / "icon.ico"))
    print("ikon dibuat di", OUT)
