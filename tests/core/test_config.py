import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.config import Settings


def _key(n: int = 32) -> str:
    return base64.b64encode(b"k" * n).decode()


def make(**kw) -> Settings:
    base = dict(
        api_key="a" * 32, storage_root=Path("/var/lib/komute"),
        storage_key_b64=_key(), storage_key_id="s1",
        manifest_key_b64=_key(), manifest_key_id="m1",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_defaults_ok():
    s = make()
    assert s.env == "dev" and s.face_match_threshold == 0.40


def test_keys_must_decode_to_32_bytes():
    with pytest.raises(ValidationError):
        make(storage_key_b64=_key(16))
    with pytest.raises(ValidationError):
        make(manifest_key_b64="not base64!!")


def test_production_rejects_dev_skip_liveness():
    with pytest.raises(ValidationError):
        make(env="production", dev_skip_liveness=True, liveness_model=Path("m.onnx"))


def test_production_requires_liveness_model():
    with pytest.raises(ValidationError):
        make(env="production")
    assert make(env="production", liveness_model=Path("m.onnx")).env == "production"


@pytest.mark.parametrize("p", [
    r"C:\Users\x\OneDrive\Desktop\store", r"C:\Users\x\OneDrive - Corp\store", "/home/x/onedrive/s",
])
def test_storage_root_inside_onedrive_rejected(p):
    with pytest.raises(ValidationError):
        make(storage_root=Path(p))


def test_production_rejects_short_api_key_dev_allows_it():
    with pytest.raises(ValidationError):
        make(env="production", liveness_model=Path("m.onnx"), api_key="short")
    assert make(api_key="short").env == "dev"
    assert make(env="production", liveness_model=Path("m.onnx"), api_key="k" * 24).env == "production"
