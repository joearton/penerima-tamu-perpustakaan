"""Titik masuk aplikasi: `library-visitor` atau `python -m library_visitor`."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

from library_visitor.config import Settings
from library_visitor.directory_api import warn_if_env_exposed
from library_visitor.extensions import ExtensionError, MemberDirectory, load_extensions
from library_visitor.face.models import download_models, missing_models

log = logging.getLogger("library_visitor")


def setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.data_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])


def lookup_cli(directory: MemberDirectory | None, number: str) -> int:
    if directory is None:
        print("Direktori anggota belum dikonfigurasi: isi DIRECTORY_* di .env", file=sys.stderr)
        return 2
    try:
        person = directory.lookup(number)
    except ExtensionError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    if person is None:
        print(f"{number}: tidak ditemukan di direktori")
        return 1
    print(" | ".join([person.member_no, person.name, person.category, person.unit, person.status]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="library-visitor")
    parser.add_argument(
        "--download-models", action="store_true", help="unduh model wajah lalu keluar"
    )
    parser.add_argument(
        "--lookup", metavar="NOMOR", help="tes direktori anggota: cari satu nomor lalu keluar"
    )
    args = parser.parse_args()

    settings = Settings.load()
    setup_logging(settings)
    env_path = settings.home / ".env"
    load_dotenv(env_path)
    warn_if_env_exposed(env_path)
    extensions = load_extensions()

    if args.lookup:
        return lookup_cli(extensions.directory, args.lookup)

    if args.download_models or missing_models(settings.models_dir):
        try:
            download_models(settings.models_dir)
        except Exception:  # jaringan, izin tulis, dll.
            log.exception("Gagal mengunduh model wajah")
            return 1
        if args.download_models:
            print(f"Model siap di {settings.models_dir}")
            return 0

    # Import Qt setelah model siap agar --download-models tetap jalan di server tanpa layar
    from pathlib import Path

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from library_visitor.db import create_session_factory
    from library_visitor.face import FaceMatcher
    from library_visitor.gallery import FaceGallery
    from library_visitor.licensing import check_stored_license
    from library_visitor.services import VisitorService
    from library_visitor.ui.license_dialog import LicenseDialog
    from library_visitor.ui.main_window import MainWindow
    from library_visitor.ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Penerima Tamu Perpustakaan")
    app.setDesktopFileName("penerima-tamu-perpustakaan")  # cocokkan ikon di Wayland/GNOME
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("ui") / "icon.png")))
    apply_theme(app)

    # Aplikasi wajib berlisensi: tanpa key valid, hanya dialog aktivasi yang tampil
    license_, reason = check_stored_license(settings.data_dir)
    if license_ is None:
        dialog = LicenseDialog(settings.data_dir, startup=True, reason=reason)
        if dialog.exec() != LicenseDialog.DialogCode.Accepted:
            return 0
        license_ = dialog.license
    log.info("Lisensi: %s", license_.describe())
    settings.licensee = license_.licensee

    sessions = create_session_factory(settings.database_path)
    service = VisitorService(
        sessions, FaceMatcher(settings.match_threshold), settings.visit_cooldown_minutes
    )
    log.info("Aplikasi dimulai, %d wajah terdaftar", service.load_matcher())
    gallery = FaceGallery(sessions)
    log.info("Galeri foto direktori: %d wajah", gallery.load())

    window = MainWindow(service, settings, extensions, gallery, license_=license_)
    window.show()
    window.start_camera()
    if settings.kiosk_on_start:
        window.open_kiosk()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
