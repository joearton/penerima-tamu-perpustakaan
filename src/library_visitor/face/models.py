"""Unduh dan lokasi file model ONNX (YuNet + SFace dari OpenCV Zoo, lisensi Apache 2.0)."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"


@dataclass(frozen=True)
class ModelFile:
    filename: str
    url: str
    min_bytes: int  # Penjaga agar file pointer Git LFS yang kecil tidak dianggap model


DETECTOR = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    200_000,
)
RECOGNIZER = ModelFile(
    "face_recognition_sface_2021dec.onnx",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    30_000_000,
)
ALL_MODELS = (DETECTOR, RECOGNIZER)


def model_path(models_dir: Path, model: ModelFile) -> Path:
    return models_dir / model.filename


def missing_models(models_dir: Path) -> list[ModelFile]:
    return [
        m
        for m in ALL_MODELS
        if not (p := model_path(models_dir, m)).exists() or p.stat().st_size < m.min_bytes
    ]


def download_models(models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    for model in missing_models(models_dir):
        target = model_path(models_dir, model)
        tmp = target.with_suffix(".part")
        print(f"Mengunduh {model.filename} ...")
        urllib.request.urlretrieve(model.url, tmp)
        if tmp.stat().st_size < model.min_bytes:
            tmp.unlink()
            raise RuntimeError(f"File {model.filename} yang diunduh tidak valid")
        tmp.replace(target)
