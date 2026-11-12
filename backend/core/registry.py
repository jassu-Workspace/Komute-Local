"""Hash-verified ONNX model registry. Hashes live in backend/models/models.lock."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

import onnxruntime as ort

from backend.core.contracts import EngineError
from backend.core.hardware import ort_session_options

Name = Literal["face_embedder", "plate_detector", "plate_ocr", "liveness"]
_FILES = {
    "face_embedder": "w600k_r50.onnx",
    "plate_detector": "yolo-v9-t-384-license-plates-end2end.onnx",
    "plate_ocr": "cct_xs_v2_global.onnx",
}
_DETECTOR = "face_detection_yunet_2023mar.onnx"


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
        self.loaded: dict[str, bool] = {n: False for n in (*_FILES, "liveness")}
        self._load_ms: dict[str, float] = {}
        self._hashes: dict[str, str] = {}

    def load(self) -> None:
        if self._sessions:
            return
        lock = json.loads(self._lock.read_text(encoding="utf-8"))
        verify_lock(self._dir, self._lock)
        for name in (*_FILES.values(), _DETECTOR):  # every file we open must be locked
            if name not in lock:
                raise ModelHashMismatch(name)
        if self._liveness is not None:
            lname = self._liveness.name
            if lname not in lock or not self._liveness.is_file() or _sha256(self._liveness) != lock[lname]:
                raise ModelHashMismatch(lname)
        sessions = {}
        for n, path in [*((n, self._dir / f) for n, f in _FILES.items()),
                        *([("liveness", self._liveness)] if self._liveness is not None else [])]:
            t = time.perf_counter()
            sessions[n] = self._open(path)
            self._load_ms[n] = round((time.perf_counter() - t) * 1000, 1)
        self._hashes = dict(lock)
        self.loaded.update({n: n in sessions for n in self.loaded})
        self._sessions = sessions  # assigned last: a failed load leaves the registry empty

    @staticmethod
    def _open(path: Path) -> ort.InferenceSession:
        return ort.InferenceSession(str(path), ort_session_options(), providers=["CPUExecutionProvider"])

    def session(self, name: Name) -> ort.InferenceSession:
        return self._sessions[name]

    def describe(self) -> list[dict]:
        """Per-model facts for monitoring: file, size, locked hash, runtime, load time, tensor signatures."""
        def io(args) -> list[dict]:
            return [{"name": a.name, "shape": [d if isinstance(d, int) else str(d) for d in (a.shape or [])], "type": a.type}
                    for a in args]

        rows = [{"role": "face_detector", "stage": "face", "file": _DETECTOR, "runtime": "OpenCV FaceDetectorYN",
                 "loaded": bool(self._sessions), "path": self.face_detector_path}]
        for n in (*_FILES, "liveness"):
            path = self._liveness if n == "liveness" else self._dir / _FILES[n]
            row = {"role": n, "stage": "face" if n in ("face_embedder", "liveness") else "vehicle",
                   "file": path.name if path else None, "runtime": "ONNX Runtime", "loaded": n in self._sessions, "path": path}
            sess = self._sessions.get(n)
            if sess is not None:
                row.update(providers=sess.get_providers(), load_ms=self._load_ms.get(n),
                           inputs=io(sess.get_inputs()), outputs=io(sess.get_outputs()))
            rows.append(row)
        for row in rows:
            path = row.pop("path")
            row["size_mb"] = round(path.stat().st_size / 1_048_576, 2) if path is not None and path.is_file() else None
            row["sha256"] = self._hashes.get(row["file"]) if row["file"] else None
            row["hash_verified"] = row["loaded"] and row["sha256"] is not None
        return rows
