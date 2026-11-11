"""Hash-verified ONNX model registry. Hashes live in backend/models/models.lock."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import onnxruntime as ort

from backend.core.contracts import EngineError
from backend.core.hardware import ort_session_options

Name = Literal["face_embedder", "plate_detector", "plate_ocr", "liveness"]
_FILES = {
    "face_embedder": "w600k_r50.onnx",
    "plate_detector": "yolo-v9-t-384-license-plates-end2end.onnx",
    "plate_ocr": "plate_ocr_ppocrv5_mobile.onnx",
}
_DETECTOR = "face_detection_yunet_2023mar.onnx"
_DICT = "plate_ocr_dict.json"


class ModelHashMismatch(EngineError):
    def __init__(self, name: str):
        super().__init__("MODEL_HASH_MISMATCH", f"model file failed hash check: {name}")
        self.name = name


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_lock(models_dir: Path, lock_path: Path) -> None:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for name, expected in lock.items():
        p = models_dir / name
        if not p.is_file() or _sha256(p) != expected:
            raise ModelHashMismatch(name)


class ModelRegistry:
    def __init__(self, models_dir: Path, lock_path: Path, liveness_path: Path | None):
        self._dir, self._lock, self._liveness = models_dir, lock_path, liveness_path
        self._sessions: dict[str, ort.InferenceSession] = {}
        self.face_detector_path = models_dir / _DETECTOR  # loaded by OpenCV (FaceDetectorYN), not ORT
        self.plate_charset: list[str] = []
        self.loaded: dict[str, bool] = {n: False for n in (*_FILES, "liveness")}

    def load(self) -> None:
        if self._sessions:
            return
        lock = json.loads(self._lock.read_text(encoding="utf-8"))
        verify_lock(self._dir, self._lock)
        for name in (*_FILES.values(), _DETECTOR, _DICT):  # every file we open must be locked
            if name not in lock:
                raise ModelHashMismatch(name)
        if self._liveness is not None:
            lname = self._liveness.name
            if lname not in lock or not self._liveness.is_file() or _sha256(self._liveness) != lock[lname]:
                raise ModelHashMismatch(lname)
        sessions = {n: self._open(self._dir / f) for n, f in _FILES.items()}
        if self._liveness is not None:
            sessions["liveness"] = self._open(self._liveness)
        # Measured: output classes = len(dict) + 2 -> [CTC blank] + dict + [space]
        chars = json.loads((self._dir / _DICT).read_text(encoding="utf-8"))
        self.plate_charset = ["", *chars, " "]
        self.loaded.update({n: n in sessions for n in self.loaded})
        self._sessions = sessions  # assigned last: a failed load leaves the registry empty

    @staticmethod
    def _open(path: Path) -> ort.InferenceSession:
        return ort.InferenceSession(str(path), ort_session_options(), providers=["CPUExecutionProvider"])

    def session(self, name: Name) -> ort.InferenceSession:
        return self._sessions[name]
