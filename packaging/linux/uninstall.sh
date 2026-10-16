#!/usr/bin/env bash
# Hapus aplikasi. Data (database, backup, .env) TIDAK dihapus kecuali dengan --purge.
set -euo pipefail
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$SHARE/penerima-tamu-perpustakaan/app"
rm -f "$HOME/.local/bin/penerima-tamu" \
      "$SHARE/applications/penerima-tamu-perpustakaan.desktop" \
      "$SHARE/icons/hicolor/256x256/apps/penerima-tamu-perpustakaan.png" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/penerima-tamu-perpustakaan.desktop"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$SHARE/penerima-tamu-perpustakaan"
  echo "Aplikasi dan seluruh data dihapus."
else
  echo "Aplikasi dihapus. Data tetap ada di $SHARE/penerima-tamu-perpustakaan (hapus dengan --purge)."
fi
