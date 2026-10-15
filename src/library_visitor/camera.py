"""Thread kamera: membaca frame, mendeteksi, dan mengenali wajah di luar thread UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from library_visitor.face import FaceEngine, FaceMatcher, Match

GREEN = (80, 200, 80)
ORANGE = (0, 165, 255)
GREY = (160, 160, 160)


@dataclass(frozen=True)
class FaceResult:
    box: tuple[int, int, int, int]
    embedding: np.ndarray | None  # None jika wajah terlalu kecil untuk dikenali
    match: Match | None


class CameraWorker(QThread):
    frame_ready = Signal(QImage, list)  # gambar beranotasi, list[FaceResult]
    failed = Signal(str)

    def __init__(
        self,
        camera_index: int,
        models_dir: Path,
        matcher: FaceMatcher,
        detect_score: float,
        min_face_size: int,
        max_faces: int = 3,
    ) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._models_dir = models_dir
        self._matcher = matcher
        self._detect_score = detect_score
        self._min_face_size = min_face_size
        self._max_faces = max_faces
        self._running = False

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def run(self) -> None:
        try:
            engine = FaceEngine(self._models_dir, self._detect_score)
        except cv2.error as exc:
            self.failed.emit(f"Gagal memuat model wajah: {exc}")
            return
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self.failed.emit(f"Kamera #{self._camera_index} tidak dapat dibuka")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.failed.emit("Gagal membaca frame dari kamera")
                    break
                frame = cv2.flip(frame, 1)  # efek cermin agar natural bagi pengunjung
                results = self._analyze(engine, frame)
                self._annotate(frame, results)
                self.frame_ready.emit(_to_qimage(frame), results)
        finally:
            cap.release()

    def _analyze(self, engine: FaceEngine, frame: np.ndarray) -> list[FaceResult]:
        results = []
        for face in engine.detect(frame)[: self._max_faces]:
            if face.size < self._min_face_size:
                results.append(FaceResult(face.box, None, None))
                continue
            emb = engine.embed(frame, face)
            results.append(FaceResult(face.box, emb, self._matcher.match(emb)))
        return results

    @staticmethod
    def _annotate(frame: np.ndarray, results: list[FaceResult]) -> None:
        for r in results:
            x, y, w, h = r.box
            if r.embedding is None:
                color, text = GREY, "Mendekat ke kamera"
            elif r.match:
                color, text = GREEN, f"{r.match.label} ({r.match.score:.2f})"
            else:
                color, text = ORANGE, "Tidak dikenal"
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, text, (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


def _to_qimage(frame: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
