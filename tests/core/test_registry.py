import shutil
from pathlib import Path

import pytest

from backend.core.registry import ModelHashMismatch, ModelRegistry, verify_lock

MODELS = Path(__file__).resolve().parents[2] / "backend" / "models"
LOCK = MODELS / "models.lock"
pytestmark = pytest.mark.models


def test_verify_lock_passes_on_true_hashes():
    verify_lock(MODELS, LOCK)


def test_verify_lock_raises_on_tampered_file(tmp_path):
    name = "face_detection_yunet_2023mar.onnx"
    shutil.copy(LOCK, tmp_path / "models.lock")
    for n in ("plate_ocr_dict.json",):
        shutil.copy(MODELS / n, tmp_path / n)
    data = bytearray((MODELS / name).read_bytes())
    data[len(data) // 2] ^= 0xFF
    (tmp_path / name).write_bytes(bytes(data))
    with pytest.raises(ModelHashMismatch) as e:
        verify_lock(tmp_path, tmp_path / "models.lock")
    assert e.value.code == "MODEL_HASH_MISMATCH"


def test_verify_lock_raises_on_missing_file(tmp_path):
    shutil.copy(LOCK, tmp_path / "models.lock")
    with pytest.raises(ModelHashMismatch):
        verify_lock(tmp_path, tmp_path / "models.lock")


def test_registry_loads_all_sessions():
    reg = ModelRegistry(MODELS, LOCK, liveness_path=None)
    reg.load()
    assert reg.loaded == {"face_embedder": True, "plate_detector": True, "plate_ocr": True, "liveness": False}
    assert reg.face_detector_path.name == "face_detection_yunet_2023mar.onnx"
    assert len(reg.plate_charset) == 18385
    assert reg.plate_charset[0] == "" and reg.plate_charset[-1] == " "
    assert reg.plate_charset[16163] == "0" and reg.plate_charset[16179] == "A"
    for n in ("face_embedder", "plate_detector", "plate_ocr"):
        assert reg.session(n) is not None
    with pytest.raises(KeyError):
        reg.session("liveness")
