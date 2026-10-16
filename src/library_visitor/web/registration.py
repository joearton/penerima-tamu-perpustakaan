"""Logika registrasi via web: foto dari kamera HP -> embedding, pencarian, dan lookup anggota.

Foto hanya diproses di memori lalu dibuang; yang disimpan hanya embedding (sama seperti
registrasi di aplikasi). Tidak bergantung pada HTTP agar mudah dites.
"""

from __future__ import annotations

import base64
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from library_visitor.config import Settings
from library_visitor.extensions import DirectoryPerson, ExtensionError, MemberDirectory
from library_visitor.face import FaceEngine, normalize
from library_visitor.services import CATEGORIES, ServiceError, VisitorService

MAX_IMAGES = 20
MAX_IMAGE_BYTES = 3 * 1024 * 1024
SEARCH_LIMIT = 10


class RegistrationError(Exception):
    """Pesan aman ditampilkan di laman web."""

    def __init__(self, message: str, status: int = 400, extra: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


@dataclass
class FaceTools:
    engine: FaceEngine
    antispoof: object | None  # AntiSpoof; None bila anti-spoofing dimatikan


def default_tools(settings: Settings) -> FaceTools:
    antispoof = None
    if settings.antispoof_enabled:
        from library_visitor.face.antispoof import AntiSpoof

        antispoof = AntiSpoof()
    return FaceTools(FaceEngine(settings.models_dir, settings.detect_score), antispoof)


def min_valid_samples(sent: int) -> int:
    return max(2, math.ceil(sent * 0.6))


def person_dict(person: DirectoryPerson, registered: bool, has_face: bool = False) -> dict:
    return {
        "member_no": person.member_no,
        "name": person.name,
        "category": person.category,
        "unit": person.unit,
        "status": person.status,
        "registered": registered,
        "has_face": has_face,
    }


class WebRegistration:
    def __init__(
        self,
        service: VisitorService,
        settings: Settings,
        directory: MemberDirectory | None = None,
        tools_factory: Callable[[Settings], FaceTools] = default_tools,
    ) -> None:
        self._service = service
        self._settings = settings
        self._directory = directory
        self._tools_factory = tools_factory
        self._tools: FaceTools | None = None
        self._lock = threading.Lock()  # model OpenCV tidak aman dipakai paralel

    # ---------- info ----------

    def meta(self) -> dict:
        s = self._settings
        directory = self._directory
        return {
            "library": s.library_name,
            "institution": s.licensee,
            "categories": list(CATEGORIES),
            "samples": s.enroll_samples,
            "lookup": directory is not None,
            "search": bool(getattr(directory, "supports_search", False)),
        }

    # ---------- anggota ----------

    def search(self, text: str) -> list[dict]:
        text = text.strip()
        if len(text) < 2:
            return []
        local = self._service.list_members(text, limit=6)
        results = [
            person_dict(
                DirectoryPerson(
                    m.member_no, m.name, m.category, m.unit or "", m.directory_status or ""
                ),
                True,
                m.face_embedding is not None,
            )
            for m in local
        ]
        if len(text) >= 3 and getattr(self._directory, "supports_search", False):
            known = {r["member_no"] for r in results}
            try:
                remote = self._directory.search(text, limit=SEARCH_LIMIT)
            except ExtensionError:
                remote = []
            results += [person_dict(p, False) for p in remote if p.member_no not in known]
        return results[:SEARCH_LIMIT]

    def lookup(self, number: str) -> dict:
        number = number.strip()
        if not number:
            raise RegistrationError("No. anggota kosong")
        member = self._service.get_member_by_no(number)
        result: dict = {"found": False, "photo": ""}
        if member is not None:
            result.update(
                person_dict(
                    DirectoryPerson(
                        member.member_no,
                        member.name,
                        member.category,
                        member.unit or "",
                        member.directory_status or "",
                    ),
                    True,
                    member.face_embedding is not None,
                ),
                found=True,
            )
        if self._directory is None:
            return result
        try:
            person = self._directory.lookup(number)
        except ExtensionError as exc:
            if member is None:
                raise RegistrationError(str(exc), 502) from None
            return result
        if person is None:
            return result
        if member is None:
            result.update(person_dict(person, False), found=True, source="direktori")
        fetch = getattr(self._directory, "fetch_photo", None)
        photo = fetch(person) if fetch else b""
        if photo:  # hanya diteruskan untuk ditampilkan, tidak disimpan
            result["photo"] = "data:image/jpeg;base64," + base64.b64encode(photo).decode()
        return result

    # ---------- wajah ----------

    def _face_tools(self) -> FaceTools:
        if self._tools is None:
            self._tools = self._tools_factory(self._settings)
        return self._tools

    def embeddings(self, images: list[bytes]) -> tuple[list[np.ndarray], list[str]]:
        """Embedding dari foto yang lolos pemeriksaan + alasan foto yang ditolak."""
        s = self._settings
        accepted: list[np.ndarray] = []
        problems: list[str] = []
        with self._lock:
            tools = self._face_tools()
            for i, data in enumerate(images, start=1):
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    problems.append(f"Foto {i}: bukan gambar yang valid")
                    continue
                faces = tools.engine.detect(frame)
                if len(faces) != 1:
                    problems.append(
                        f"Foto {i}: "
                        + ("wajah tidak terdeteksi" if not faces else "lebih dari satu wajah")
                    )
                    continue
                face = faces[0]
                if face.size < s.min_face_size:
                    problems.append(f"Foto {i}: wajah terlalu kecil, dekatkan kamera")
                    continue
                if tools.antispoof is not None:
                    if tools.antispoof.real_score(frame, face) < s.antispoof_threshold:
                        problems.append(f"Foto {i}: terdeteksi foto/layar, gunakan wajah asli")
                        continue
                accepted.append(tools.engine.embed(frame, face))
        return accepted, problems

    def register(self, data: dict, images: list[bytes]) -> dict:
        number = str(data.get("member_no", "")).strip()
        name = str(data.get("name", "")).strip()
        category = str(data.get("category", "Umum"))
        if category not in CATEGORIES:
            category = "Umum"
        if not number or not name:
            raise RegistrationError("No. anggota dan nama wajib diisi")
        if images and not data.get("consent"):
            raise RegistrationError("Persetujuan data biometrik wajib dicentang")
        if len(images) > MAX_IMAGES:
            raise RegistrationError(f"Terlalu banyak foto (maksimal {MAX_IMAGES})")

        samples: list[np.ndarray] = []
        if images:
            samples, problems = self.embeddings(images)
            needed = min_valid_samples(len(images))
            if len(samples) < needed:
                raise RegistrationError(
                    f"Hanya {len(samples)} dari {len(images)} foto yang bisa dipakai "
                    f"(minimal {needed}). Ulangi pengambilan wajah.",
                    422,
                    {"problems": problems},
                )
            existing = self._service.get_member_by_no(number)
            mean = normalize(np.mean(samples, axis=0))
            best = self._service.matcher.best(mean, exclude=existing.id if existing else None)
            if (
                best is not None
                and best.score >= self._service.matcher.threshold
                and not data.get("confirm_duplicate")
            ):
                raise RegistrationError(
                    f"Wajah ini mirip dengan {best.label} (skor {best.score:.2f}). "
                    "Pastikan orangnya benar, lalu simpan ulang dengan konfirmasi.",
                    409,
                    {"duplicate": best.label, "score": round(best.score, 2)},
                )
        status = str(data.get("status", "")).strip() if data.get("from_directory") else None
        try:
            member = self._service.save_member(
                number,
                name,
                category,
                samples,
                unit=str(data.get("unit", "")),
                directory_status=status,
            )
        except ServiceError as exc:
            raise RegistrationError(str(exc)) from None
        return {
            "member_no": member.member_no,
            "name": member.name,
            "face_saved": bool(samples),
            "samples": len(samples),
        }
