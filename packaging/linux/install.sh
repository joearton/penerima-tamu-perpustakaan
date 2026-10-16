#!/usr/bin/env bash
# Pasang untuk user saat ini (tanpa sudo). Opsi: --autostart (jalan otomatis saat login)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/penerima-tamu-perpustakaan/app"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

mkdir -p "$DEST" "$BIN" "$APPS" "$ICONS"
rm -rf "$DEST"
cp -r "$SRC/app" "$DEST"
ln -sf "$DEST/PenerimaTamu" "$BIN/penerima-tamu"
cp "$SRC/icon.png" "$ICONS/penerima-tamu-perpustakaan.png"

DESKTOP="[Desktop Entry]
Type=Application
Name=Penerima Tamu Perpustakaan
Comment=Pencatat pengunjung perpustakaan dengan face recognition
Exec=$DEST/PenerimaTamu
Icon=penerima-tamu-perpustakaan
Terminal=false
Categories=Office;Education;
StartupWMClass=penerima-tamu-perpustakaan"
echo "$DESKTOP" > "$APPS/penerima-tamu-perpustakaan.desktop"

if [ "${1:-}" = "--autostart" ]; then
  mkdir -p "$AUTOSTART"
  echo "$DESKTOP" > "$AUTOSTART/penerima-tamu-perpustakaan.desktop"
  echo "Autostart aktif."
fi

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/penerima-tamu-perpustakaan"
echo "Terpasang. Jalankan dari menu aplikasi atau: penerima-tamu"
echo "Data & konfigurasi (.env) ada di: $DATA"
echo "Akses kamera: pastikan user ada di grup 'video' (sudo usermod -aG video \$USER)."
