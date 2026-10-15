"""Deteksi (YuNet) dan ekstraksi embedding wajah (SFace) memakai modul DNN OpenCV.

Objek detektor OpenCV tidak thread-safe: buat satu FaceEngine per thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from library_visitor.face.models import DETECTOR, RECOGNIZER, model_path

# OpenCV 5 mencetak warning "Targets are not supported by the new graph engine" yang tidak relevan
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)


@dataclass(frozen=True)
class DetectedFace:
    raw: np.ndarray  # 15 nilai: x, y, w, h, 5 landmark (x, y), skor

    @property
    def box(self) -> tuple[int, int, int, int]:
        x, y, w, h = self.raw[:4]
        return int(x), int(y), int(w), int(h)

    @property
    def score(self) -> float:
        return float(self.raw[14])

    @property
    def size(self) -> int:
        return min(self.box[2], self.box[3])


def normalize(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class FaceEngine:
    def __init__(self, models_dir: Path, score_threshold: float = 0.85) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path(models_dir, DETECTOR)), "", (320, 320), score_threshold, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(model_path(models_dir, RECOGNIZER)), "")
        self._input_size: tuple[int, int] | None = None

    def detect(self, frame: np.ndarray) -> list[DetectedFace]:
        h, w = frame.shape[:2]
        if self._input_size != (w, h):
            self._detector.setInputSize((w, h))
            self._input_size = (w, h)
        _, faces = self._detector.detect(frame)
        if faces is None:
            return []
        return sorted((DetectedFace(f) for f in faces), key=lambda f: f.size, reverse=True)

    def embed(self, frame: np.ndarray, face: DetectedFace) -> np.ndarray:
        """Embedding 128 dimensi yang sudah dinormalisasi (dot product = cosine similarity)."""
        aligned = self._recognizer.alignCrop(frame, face.raw)
        return normalize(self._recognizer.feature(aligned))
