import base64

import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.core  # noqa: F401
import cv2

from backend.app.main import create_app
from backend.core.config import Settings
from backend.core.contracts import EngineError
from backend.core.idempotency import IdempotencyConflict, save
from backend.core.imaging import IMAGE_KEYS, decode_image
from storage import Cipher, LocalStore

KEY = "test-api-key-123"


def b64(b):
    return base64.b64encode(b).decode()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key=KEY, storage_root=tmp_path / "store", storage_key_b64=b64(b"s" * 32), storage_key_id="s1",
        manifest_key_b64=b64(b"m" * 32), manifest_key_id="m1", dev_skip_liveness=True, max_upload_bytes=200_000,
    )


class FakeEngine:
    def __init__(self, settings, mode="ok"):
        self.store = LocalStore(settings.storage_root, Cipher(b"s" * 32, "s1"))
        self.mode, self.seen, self.models = mode, [], {"face_embedder": True, "plate_detector": True, "plate_ocr": True, "liveness": False}

    def verify(self, inp):
        self.seen.append(inp)
        for k in IMAGE_KEYS:
            decode_image(inp.image_bytes[k], 2048)  # raises InputError exactly like the real engine
        if self.mode == "conflict":
            raise IdempotencyConflict(inp.request_id)
        if self.mode == "error":
            raise EngineError("ENGINE_ERROR")
        return {"request_id": inp.request_id, "decision": "APPROVED", "reasons": []}

    def health_info(self):
        return {"models_loaded": self.models}


def make(settings, mode="ok"):
    eng = FakeEngine(settings, mode)
    return TestClient(create_app(settings, eng)), eng


def jpg(seed=0):
    return cv2.imencode(".jpg", np.random.default_rng(seed).integers(0, 255, (40, 40, 3), dtype=np.uint8))[1].tobytes()


FIELDS = {
    "request_id": "req-1", "driver_id": "drv-1", "consent_at": "2026-11-11T12:00:00Z", "consent_policy_version": "v1",
    "claimed.full_name": "Alex Tester", "claimed.date_of_birth": "1990-03-15", "claimed.licence_number": "T1234-56789-01234",
    "claimed.issuing_province": "ON", "claimed.plate_number": "ABC123", "claimed.vehicle_colour": "Grey",
}


def post(client, fields=None, files=None, key=KEY, drop=()):
    data = {k: v for k, v in (fields or FIELDS).items() if k not in drop}
    f = {k: (f"{k}.jpg", v, "image/jpeg") for k, v in (files or {k: jpg(i) for i, k in enumerate(IMAGE_KEYS)}).items()}
    headers = {"X-API-Key": key} if key else {}
    return client.post("/v1/verify", data=data, files=f, headers=headers)


def code(r):
    return r.json()["error"]["code"]


def test_missing_and_wrong_key_401(settings):
    c, _ = make(settings)
    assert post(c, key=None).status_code == 401 and code(post(c, key=None)) == "UNAUTHORIZED"
    assert post(c, key="nope").status_code == 401


def test_happy_path_returns_engine_response(settings):
    c, eng = make(settings)
    r = post(c)
    assert r.status_code == 200 and r.json()["decision"] == "APPROVED"
    inp = eng.seen[0]
    assert inp.request_id == "req-1" and inp.claimed.date_of_birth.isoformat() == "1990-03-15"
    assert inp.consent_at.tzinfo is not None and len(inp.payload_sha256) == 64


def test_missing_consent_422(settings):
    c, _ = make(settings)
    for drop in (("consent_at",), ("consent_policy_version",), ("consent_at", "consent_policy_version")):
        r = post(c, drop=drop)
        assert r.status_code == 422 and code(r) == "CONSENT_REQUIRED"


def test_consent_without_timezone_422(settings):
    c, _ = make(settings)
    r = post(c, {**FIELDS, "consent_at": "2026-11-11T12:00:00"})
    assert r.status_code == 422 and code(r) == "INVALID_FIELD"


def test_bad_province_422_and_nf_accepted_as_nl(settings):
    c, eng = make(settings)
    assert code(post(c, {**FIELDS, "claimed.issuing_province": "ZZ"})) == "INVALID_FIELD"
    assert post(c, {**FIELDS, "claimed.issuing_province": "NF", "request_id": "req-nf"}).status_code == 200
    assert eng.seen[-1].claimed.issuing_province == "NL"


def test_missing_field_and_bad_date_422(settings):
    c, _ = make(settings)
    assert code(post(c, drop=("claimed.full_name",))) == "MISSING_FIELD"
    assert code(post(c, {**FIELDS, "claimed.date_of_birth": "15/03/1990"})) == "INVALID_FIELD"
    assert code(post(c, {**FIELDS, "claimed.vehicle_year": "abc"})) == "INVALID_FIELD"


def test_request_id_rejects_path_characters(settings):
    c, _ = make(settings)
    for bad in ("../x", "a/b", "a b", "x" * 65):
        r = post(c, {**FIELDS, "request_id": bad})
        assert r.status_code == 422 and code(r) == "INVALID_FIELD"


def test_missing_image_422(settings):
    c, _ = make(settings)
    files = {k: jpg(i) for i, k in enumerate(IMAGE_KEYS) if k != "vehicle"}
    r = post(c, files=files)
    assert r.status_code == 422 and code(r) == "MISSING_FIELD"


def test_oversize_upload_422(settings):
    c, _ = make(settings)
    files = {k: jpg(i) for i, k in enumerate(IMAGE_KEYS)}
    files["selfie"] = b"\xff\xd8\xff" + b"0" * 250_000
    r = post(c, files=files)
    assert r.status_code == 422 and code(r) == "IMAGE_TOO_LARGE"


def test_random_bytes_image_422_not_500(settings):
    c, _ = make(settings)
    files = {k: jpg(i) for i, k in enumerate(IMAGE_KEYS)}
    files["licence_back"] = b"this is not an image at all"
    r = post(c, files=files)
    assert r.status_code == 422 and code(r) == "INVALID_IMAGE"


def test_busy_returns_503_with_retry_after_and_gate_releases(settings):
    c, _ = make(settings)
    assert c.app.state.gate.try_acquire()
    r = post(c)
    assert r.status_code == 503 and code(r) == "BUSY" and r.headers["Retry-After"] == str(settings.retry_after_s)
    c.app.state.gate.release()
    assert post(c).status_code == 200
    assert post(c, files={k: b"x" for k in IMAGE_KEYS}).status_code == 422
    assert post(c, {**FIELDS, "request_id": "req-2"}).status_code == 200  # gate released after a failed request


def test_conflict_409(settings):
    c, _ = make(settings, "conflict")
    r = post(c)
    assert r.status_code == 409 and code(r) == "REQUEST_ID_CONFLICT"


def test_engine_error_500_has_no_decision_key(settings):
    c, _ = make(settings, "error")
    r = post(c)
    assert r.status_code == 500 and code(r) == "ENGINE_ERROR" and set(r.json()) == {"error"}


def test_health_no_secrets_and_degraded(settings):
    c, eng = make(settings)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and KEY not in r.text
    eng.models["plate_ocr"] = False
    r = c.get("/health")
    assert r.status_code == 503 and r.json()["status"] == "degraded"


def test_sessions_endpoint(settings):
    c, eng = make(settings)
    assert c.get("/v1/sessions/req-9", headers={"X-API-Key": KEY}).status_code == 404
    save(eng.store, "req-9", "drv", "h" * 64, {"decision": "REJECTED"})
    r = c.get("/v1/sessions/req-9", headers={"X-API-Key": KEY})
    assert r.status_code == 200 and r.json() == {"decision": "REJECTED"}
    assert c.get("/v1/sessions/req-9").status_code == 401


def test_payload_hash_changes_with_any_input(settings):
    c, eng = make(settings)
    post(c)
    post(c, {**FIELDS, "request_id": "req-1", "claimed.plate_number": "ZZZ999"})
    files = {k: jpg(i) for i, k in enumerate(IMAGE_KEYS)}
    files["vehicle"] = jpg(99)
    post(c, files=files)
    assert len({i.payload_sha256 for i in eng.seen}) == 3


def test_index_served(settings):
    c, _ = make(settings)
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "Komute-Local" in r.text
