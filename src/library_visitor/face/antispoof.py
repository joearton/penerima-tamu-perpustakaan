"""Deteksi wajah palsu (foto cetak / layar HP) dengan MiniFASNet (Minivision, Apache-2.0).

Dua model dijalankan pada crop wajah berskala berbeda lalu dirata-rata, mengikuti
implementasi aslinya. Model disertakan di paket (folder antispoof_models/), lihat NOTICE di sana.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from library_visitor.face.engine import DetectedFace

MODEL_DIR = Path(__file__).with_name("antispoof_models")
# (file model, skala crop relatif terhadap kotak wajah)
MODELS = (("2.7_80x80_MiniFASNetV2.onnx", 2.7), ("4_0_0_80x80_MiniFASNetV1SE.onnx", 4.0))
INPUT_SIZE = 80
REAL_CLASS = 1


def crop_box(src_w: int, src_h: int, box: tuple[int, int, int, int], scale: float):
    """Perbesar kotak wajah dengan `scale` dan geser agar tetap di dalam gambar."""
    x, y, box_w, box_h = box
    scale = min((src_h - 1) / box_h, (src_w - 1) / box_w, scale)
    new_w, new_h = box_w * scale, box_h * scale
    cx, cy = x + box_w / 2, y + box_h / 2
    left, top, right, bottom = cx - new_w / 2, cy - new_h / 2, cx + new_w / 2, cy + new_h / 2
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > src_w - 1:
        left -= right - src_w + 1
        right = src_w - 1
    if bottom > src_h - 1:
        top -= bottom - src_h + 1
        bottom = src_h - 1
    return int(left), int(top), int(right), int(bottom)


class AntiSpoof:
    """Tidak thread-safe (sama seperti FaceEngine): buat satu per thread."""

    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        self._nets = [
            (cv2.dnn.readNetFromONNX(str(model_dir / name)), scale) for name, scale in MODELS
        ]

    def real_score(self, frame: np.ndarray, face: DetectedFace) -> float:
        """Probabilitas wajah asli (0-1)."""
        h, w = frame.shape[:2]
        x, y, bw, bh = face.box
        if bw <= 0 or bh <= 0:
            return 0.0
        total = 0.0
        for net, scale in self._nets:
            left, top, right, bottom = crop_box(w, h, (x, y, bw, bh), scale)
            patch = frame[max(top, 0) : bottom + 1, max(left, 0) : right + 1]
            if patch.size == 0:
                return 0.0
            patch = cv2.resize(patch, (INPUT_SIZE, INPUT_SIZE)).astype(np.float32)
            # Model dilatih dengan piksel BGR mentah 0-255 (tanpa normalisasi)
            net.setInput(cv2.dnn.blobFromImage(patch))
            total += float(net.forward().reshape(-1)[REAL_CLASS])
        return total / len(self._nets)
