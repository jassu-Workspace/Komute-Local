import base64
import logging
from datetime import date, datetime, timezone

import numpy as np
import pytest

import backend.core  # noqa: F401
import cv2

from backend.core.aamva import AamvaRecord
from backend.core.audit import session_prefix, verify_session
from backend.core.config import Settings
from backend.core.contracts import (
    Advisory,
    Claimed,
    EngineError,
    InputError,
    Reason,
    ReasonCode,
    StageResult,
)
from backend.core.idempotency import IdempotencyConflict
from backend.core.imaging import IMAGE_KEYS
from backend.core.pipeline import Engine, Stages, VerifyInput
from storage import Cipher, LocalStore

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
MKEY = b"m" * 32
SECRET_NAME, SECRET_LICENCE, SECRET_PLATE = "Zelda Quuxington", "Q99887766554433", "ZQX987"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key="k", storage_root=tmp_path / "store", storage_key_b64=b64(b"s" * 32), storage_key_id="s1",
        manifest_key_b64=b64(MKEY), manifest_key_id="m1", dev_skip_liveness=True,
    )


@pytest.fixture
def store(settings):
    return LocalStore(settings.storage_root, Cipher(b"s" * 32, "s1"))


def jpeg(seed=0, size=64):
    img = np.random.default_rng(seed).integers(0, 255, (size, size, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def claimed():
    return Claimed(SECRET_NAME, date(1990, 1, 1), SECRET_LICENCE, "ON", SECRET_PLATE, "Red")


def inp(request_id="r1", payload="p" * 64, images=None):
    return VerifyInput(
        request_id, "d1", NOW, "v1", claimed(),
        images or {k: jpeg(i) for i, k in enumerate(IMAGE_KEYS)}, payload,
    )


class Fakes:
    def __init__(self, barcode_reasons=(), face_reasons=(), vehicle_reasons=(), vehicle_adv=(), face_raises=False):
        self.calls = []
        self.barcode_reasons, self.face_reasons = list(barcode_reasons), list(face_reasons)
        self.vehicle_reasons, self.vehicle_adv, self.face_raises = list(vehicle_reasons), list(vehicle_adv), face_raises

    def stages(self, skipped=False):
        def barcode(img, c, now):
            self.calls.append("barcode")
            r = StageResult("barcode", True, [Reason.of(x) for x in self.barcode_reasons], details={"readable": True})
            return r, AamvaRecord("636012", "09", {"DAQ": SECRET_LICENCE})

        def face(selfie, front):
            self.calls.append("face")
            if self.face_raises:
                raise RuntimeError(f"boom {SECRET_NAME}")
            crop = np.zeros((112, 112, 3), np.uint8)
            return StageResult("face", True, [Reason.of(x) for x in self.face_reasons],
                               details={"similarity": 0.9}, crops={"selfie_face": crop})

        def vehicle(img, c):
            self.calls.append("vehicle")
            return StageResult("vehicle", True, [Reason.of(x) for x in self.vehicle_reasons],
                               list(self.vehicle_adv), {"plate_read": "ZQX987"}, crops={"plate": np.zeros((20, 60, 3), np.uint8)})

        return Stages(barcode, face, vehicle, liveness_skipped=skipped)


def engine(settings, store, fakes, skipped=False):
    return Engine(settings, store, fakes.stages(skipped), clock=lambda: NOW)


def test_all_pass_approved_and_session_verifies(settings, store):
    resp = engine(settings, store, Fakes()).verify(inp())
    assert resp["decision"] == "APPROVED" and resp["reasons"] == []
    assert set(resp) == {"request_id", "decision", "reasons", "stages", "advisories", "timings_ms", "rss_mb", "memory_trace", "audit"}
    assert resp["stages"]["barcode"]["ran"] and resp["audit"]["key_id"] == "m1"
    report = verify_session(store, session_prefix("d1", "r1"), MKEY)
    assert report.ok
    tr = resp["memory_trace"]
    assert len(tr["points"]) >= 2 and tr["peak_mb"] >= tr["start_mb"] and [m[0] for m in tr["marks"]][-1] == "saved"
    keys = {k.split("/", 3)[3] for k in store.list_prefix(session_prefix("d1", "r1"))}
    assert {"originals/selfie.jpg", "cropped/plate.webp", "compressed/vehicle.webp", "record.json", "manifest.json"} <= keys


def test_stage1_fail_skips_others_and_is_rejected(settings, store):
    f = Fakes(barcode_reasons=[ReasonCode.BARCODE_UNREADABLE])
    resp = engine(settings, store, f).verify(inp())
    assert f.calls == ["barcode"] and resp["decision"] == "REJECTED"
    assert resp["stages"]["face"] == {"ran": False} and resp["stages"]["vehicle"] == {"ran": False}
    assert resp["reasons"][0]["retryable"] is True


def test_stage2_and_3_failures_reported_together(settings, store):
    f = Fakes(face_reasons=[ReasonCode.FACE_MISMATCH], vehicle_reasons=[ReasonCode.PLATE_NOT_FOUND])
    resp = engine(settings, store, f).verify(inp())
    assert [r["code"] for r in resp["reasons"]] == ["FACE_MISMATCH", "PLATE_NOT_FOUND"]
    assert resp["decision"] == "REJECTED"


def test_stage_crash_raises_engine_error_never_approved(settings, store):
    with pytest.raises(EngineError):
        engine(settings, store, Fakes(face_raises=True)).verify(inp())
    assert not store.exists(session_prefix("d1", "r1") + "/manifest.json")  # nothing was sealed
    assert not store.exists("requests/r1.json")  # and no decision was remembered


def test_storage_failure_raises_engine_error(settings, store):
    real_put = store.put

    def flaky(key, data):
        if "compressed" in key:
            raise OSError("disk full")
        real_put(key, data)

    store.put = flaky
    with pytest.raises(EngineError):
        engine(settings, store, Fakes()).verify(inp())


def test_idempotent_replay_returns_same_response_without_running_stages(settings, store):
    f = Fakes()
    e = engine(settings, store, f)
    first = e.verify(inp())
    calls = len(f.calls)
    assert e.verify(inp()) == first and len(f.calls) == calls


def test_conflict_on_changed_payload(settings, store):
    e = engine(settings, store, Fakes())
    e.verify(inp())
    with pytest.raises(IdempotencyConflict):
        e.verify(inp(payload="q" * 64))


def test_input_error_stores_nothing(settings, store):
    bad = {k: jpeg(i) for i, k in enumerate(IMAGE_KEYS)}
    bad["vehicle"] = b"not an image"
    with pytest.raises(InputError):
        engine(settings, store, Fakes()).verify(inp(images=bad))
    assert store.list_prefix(session_prefix("d1", "r1")) == []


def test_crash_mid_session_then_retry_same_id_succeeds(settings, store):
    real_put = store.put
    state = {"fail": True}

    def flaky(key, data):
        if state["fail"] and "compressed/vehicle" in key:
            raise OSError("killed")
        real_put(key, data)

    store.put = flaky
    e = engine(settings, store, Fakes())
    with pytest.raises(EngineError):
        e.verify(inp())
    state["fail"] = False
    resp = e.verify(inp())
    assert resp["decision"] == "APPROVED" and verify_session(store, session_prefix("d1", "r1"), MKEY).ok


def test_no_pii_in_logs_or_response(settings, store, caplog):
    caplog.set_level(logging.DEBUG)
    resp = engine(settings, store, Fakes()).verify(inp())
    with pytest.raises(EngineError):
        engine(settings, store, Fakes(face_raises=True)).verify(inp("r2"))
    text = caplog.text + repr(resp)
    for secret in (SECRET_NAME, SECRET_LICENCE, "1990-01-01"):
        assert secret not in text


def test_full_barcode_fields_only_when_enabled(settings, store):
    assert "barcode_fields" not in engine(settings, store, Fakes()).verify(inp())
    on = settings.model_copy(update={"response_barcode_fields": True})
    assert engine(on, store, Fakes()).verify(inp("r2"))["barcode_fields"] == {"DAQ": SECRET_LICENCE}


def test_advisories_propagate_and_dev_skip_is_flagged(settings, store):
    f = Fakes(vehicle_adv=[Advisory.COLOUR_MISMATCH])
    resp = engine(settings, store, f, skipped=True).verify(inp())
    assert resp["advisories"] == ["COLOUR_MISMATCH", "LIVENESS_SKIPPED_DEV"] and resp["decision"] == "APPROVED"


def test_record_is_sealed_with_consent_and_barcode_fields(settings, store):
    import json

    engine(settings, store, Fakes()).verify(inp())
    rec = json.loads(store.get(session_prefix("d1", "r1") + "/record.json"))
    assert rec["consent_policy_version"] == "v1" and rec["consent_at"].startswith("2026-11-11")
    assert rec["barcode_fields"]["DAQ"] == SECRET_LICENCE and rec["decision"] == "APPROVED"


def test_compressed_tier_is_capped_originals_are_untouched(settings, store):
    big = cv2.imencode(".jpg", np.random.default_rng(5).integers(0, 255, (1500, 2000, 3), dtype=np.uint8))[1].tobytes()
    images = {k: big for k in IMAGE_KEYS}
    engine(settings, store, Fakes()).verify(inp(images=images))
    prefix = session_prefix("d1", "r1")
    comp = cv2.imdecode(np.frombuffer(store.get(f"{prefix}/compressed/vehicle.webp"), np.uint8), cv2.IMREAD_COLOR)
    assert max(comp.shape[:2]) == settings.compressed_max_side == 1280
    assert store.get(f"{prefix}/originals/vehicle.jpg") == big
