# PyInstaller spec: build dengan `pyinstaller packaging/penerima-tamu.spec` dari root proyek.
# Model YuNet/SFace harus sudah ada di models/ (jalankan `library-visitor --download-models`).
from pathlib import Path

ROOT = Path(SPECPATH).parent
MODELS = ["face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"]
for name in MODELS:
    if not (ROOT / "models" / name).exists():
        raise SystemExit(f"models/{name} belum ada: jalankan `library-visitor --download-models`")

datas = [(str(ROOT / "models" / name), "models") for name in MODELS] + [
    (str(ROOT / "src/library_visitor/face/antispoof_models"), "library_visitor/face/antispoof_models"),
    (str(ROOT / "src/library_visitor/ui/icon.png"), "library_visitor/ui"),
    (str(ROOT / "src/library_visitor/ui/assets"), "library_visitor/ui/assets"),
    (str(ROOT / "src/library_visitor/web/static"), "library_visitor/web/static"),
    (str(ROOT / "src/library_visitor/docs"), "library_visitor/docs"),
]

a = Analysis(
    [str(ROOT / "packaging/launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PenerimaTamu",
    console=False,
    icon=str(ROOT / "packaging/icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="PenerimaTamu")
