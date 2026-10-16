#!/usr/bin/env bash
# Build paket Linux: dist/penerima-tamu-perpustakaan-<versi>-linux-x86_64.tar.gz
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
NAME="penerima-tamu-perpustakaan-${VERSION}-linux-$(uname -m)"
PY="${PYTHON:-.venv/bin/python}"

if [ ! -x "$PY" ]; then
  python3 -m venv .venv
  PY=.venv/bin/python
fi
"$PY" -m pip install -q -e ".[build]"
LV_HOME="$ROOT" "$PY" -m library_visitor --download-models
"$PY" -m PyInstaller --noconfirm --clean packaging/penerima-tamu.spec

STAGE="dist/$NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -r dist/PenerimaTamu "$STAGE/app"
cp packaging/icon.png "$STAGE/icon.png"
cp packaging/linux/install.sh packaging/linux/uninstall.sh "$STAGE/"
cp README.md .env.example "$STAGE/"
chmod +x "$STAGE"/install.sh "$STAGE"/uninstall.sh
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
echo "Selesai: dist/$NAME.tar.gz"
