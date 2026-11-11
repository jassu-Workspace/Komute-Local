import json
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
    data = bytearray((MODELS / name).read_bytes())
    data[len(data) // 2] ^= 0xFF
    (tmp_path / name).write_bytes(bytes(data))
    with pytest.raises(ModelHashMismatch) as e:
        verify_lock(tmp_path, tmp_path / "models.lock")
    assert e.value.code == "MODEL_HASH_MISMATCH"
    assert e.value.name == name


def test_verify_lock_raises_on_missing_file(tmp_path):
    shutil.copy(LOCK, tmp_path / "models.lock")
    with pytest.raises(ModelHashMismatch):
        verify_lock(tmp_path, tmp_path / "models.lock")


def test_registry_loads_all_sessions():
    reg = ModelRegistry(MODELS, LOCK, liveness_path=None)
    reg.load()
    assert reg.loaded == {"face_embedder": True, "plate_detector": True, "plate_ocr": True, "liveness": False}
    assert reg.face_detector_path.name == "face_detection_yunet_2023mar.onnx"
    for n in ("face_embedder", "plate_detector", "plate_ocr"):
        assert reg.session(n) is not None
    with pytest.raises(KeyError):
        reg.session("liveness")


def test_load_rejects_lock_missing_an_entry(tmp_path):
    lock = json.loads(LOCK.read_text())
    del lock["w600k_r50.onnx"]
    (tmp_path / "models.lock").write_text(json.dumps(lock))
    reg = ModelRegistry(MODELS, tmp_path / "models.lock", liveness_path=None)
    with pytest.raises(ModelHashMismatch) as e:
        reg.load()
    assert e.value.name == "w600k_r50.onnx"
    with pytest.raises(KeyError):
        reg.session("face_embedder")


def test_liveness_file_must_be_locked(tmp_path):
    live = tmp_path / "liveness.onnx"
    shutil.copy(MODELS / "w600k_r50.onnx", live)  # stand-in file, not in the lock
    reg = ModelRegistry(MODELS, LOCK, liveness_path=live)
    with pytest.raises(ModelHashMismatch) as e:
        reg.load()
    assert e.value.name == "liveness.onnx"
    lock = json.loads(LOCK.read_text())
    lock["liveness.onnx"] = "0" * 64  # wrong hash
    (tmp_path / "models.lock").write_text(json.dumps(lock))
    with pytest.raises(ModelHashMismatch):
        ModelRegistry(MODELS, tmp_path / "models.lock", liveness_path=live).load()


def test_load_twice_is_noop():
    reg = ModelRegistry(MODELS, LOCK, liveness_path=None)
    reg.load()
    first = reg.session("plate_ocr")
    reg.load()
    assert reg.session("plate_ocr") is first


def test_failed_load_leaves_registry_unloaded(tmp_path):
    reg = ModelRegistry(MODELS, LOCK, liveness_path=tmp_path / "missing.onnx")
    with pytest.raises(ModelHashMismatch):
        reg.load()
    assert not any(reg.loaded.values())
    with pytest.raises(KeyError):
        reg.session("face_embedder")
