import numpy as np

from library_visitor.face.antispoof import AntiSpoof, crop_box
from library_visitor.face.engine import DetectedFace


def test_crop_box_scales_and_stays_inside_image():
    # Kotak di tengah: diperbesar 2x di sekitar pusat
    assert crop_box(1000, 1000, (400, 400, 100, 100), 2.0) == (350, 350, 550, 550)
    # Kotak di pojok kiri atas: digeser agar tidak keluar gambar
    left, top, right, bottom = crop_box(640, 480, (0, 0, 100, 100), 4.0)
    assert (left, top) == (0, 0) and right <= 639 and bottom <= 479
    # Skala dibatasi ukuran gambar
    left, top, right, bottom = crop_box(200, 200, (50, 50, 100, 100), 4.0)
    assert left >= 0 and top >= 0 and right <= 199 and bottom <= 199


def test_model_loads_and_returns_probability():
    raw = np.zeros(15, dtype=np.float32)
    raw[:4] = (200, 150, 160, 160)
    frame = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    score = AntiSpoof().real_score(frame, DetectedFace(raw))
    assert 0.0 <= score <= 1.0
