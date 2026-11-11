"""The verification engine: ingest, stages, decision, audit. Fails closed: a fault is an error, never a decision."""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np

from storage import BlobStore, Cipher, LocalStore

from . import hardware
from .aamva import AamvaRecord
from .audit import SessionWriter, session_prefix
from .config import Settings
from .contracts import (
    Advisory,
    Claimed,
    EngineError,
    InputError,
    Reason,
    StageResult,
)
from .idempotency import IdempotencyConflict, lookup, save
from .imaging import IMAGE_KEYS, decode_image, encode_webp

log = logging.getLogger("komute.engine")

COMPRESS_QUALITY = {"selfie": 80, "licence_front": 70, "licence_back": 70, "vehicle": 85}


@dataclass(frozen=True)
class VerifyInput:
    request_id: str
    driver_id: str
    consent_at: datetime
    consent_policy_version: str
    claimed: Claimed
    image_bytes: dict[str, bytes]
    payload_sha256: str


@dataclass
class Stages:
    """The three stages as callables, so tests can inject fakes and a stage crash can be simulated."""

    barcode: Callable[[np.ndarray, Claimed, datetime], tuple[StageResult, Optional[AamvaRecord]]]
    face: Callable[[np.ndarray, np.ndarray], StageResult]
    vehicle: Callable[[np.ndarray, Claimed], StageResult]
    liveness_skipped: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _skipped(name: str) -> StageResult:
    return StageResult(name=name, ran=False)  # type: ignore[arg-type]


class Engine:
    def __init__(
        self, settings: Settings, store: BlobStore, stages: Stages, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._s = settings
        self._store = store
        self._stages = stages
        self._clock = clock
        self._manifest_key = base64.b64decode(settings.manifest_key_b64.get_secret_value())
        self.health_info: Callable[[], dict] = lambda: {"models_loaded": {}}

    @property
    def store(self) -> BlobStore:
        return self._store

    def verify(self, inp: VerifyInput) -> dict:
        cached = lookup(self._store, inp.request_id, inp.payload_sha256)  # may raise IdempotencyConflict
        if cached is not None:
            return cached
        try:
            return self._run(inp)
        except (InputError, IdempotencyConflict):
            raise
        except Exception as e:  # the one fail-closed boundary: any fault is an error, never a decision
            log.error("engine fault request_id=%s type=%s", inp.request_id, type(e).__name__)
            raise EngineError("ENGINE_ERROR") from e
        finally:
            hardware.trim_heap()

    def _run(self, inp: VerifyInput) -> dict:
        t_start = time.perf_counter()
        now = self._clock()
        images = {k: decode_image(inp.image_bytes[k], self._s.max_image_side) for k in IMAGE_KEYS}

        prefix = session_prefix(inp.driver_id, inp.request_id)
        self._store.delete_prefix(prefix)  # a retry starts clean: leftovers of a crashed run are never trusted
        writer = SessionWriter(self._store, prefix, self._manifest_key, self._s.manifest_key_id, now)
        for k in IMAGE_KEYS:
            writer.put(f"originals/{k}.{_ext(inp.image_bytes[k])}", inp.image_bytes[k])

        barcode, record = self._stages.barcode(images["licence_back"], inp.claimed, now)
        if barcode.reasons:
            face, vehicle = _skipped("face"), _skipped("vehicle")
        else:
            face = self._stages.face(images["selfie"], images["licence_front"])
            vehicle = self._stages.vehicle(images["vehicle"], inp.claimed)
        results = [barcode, face, vehicle]

        reasons: list[Reason] = []
        for r in results:
            for reason in r.reasons:
                if all(x.code != reason.code for x in reasons):
                    reasons.append(reason)
        decision = "APPROVED" if all(r.ran for r in results) and not reasons else "REJECTED"
        advisories = [a.value for r in results for a in r.advisories]
        if self._stages.liveness_skipped:
            advisories.append(Advisory.LIVENESS_SKIPPED_DEV.value)

        for r in results:
            for name, crop in r.crops.items():
                writer.put(f"cropped/{name}.webp", encode_webp(crop, 90))
        for k in IMAGE_KEYS:
            writer.put(f"compressed/{k}.webp", encode_webp(images[k], COMPRESS_QUALITY[k]))

        timings = {"total": 0.0}
        for r in results:
            timings[r.name] = round(sum(r.timings_ms.values()), 1)
        stage_view: dict[str, Any] = {r.name: {"ran": r.ran, **r.details} for r in results}
        record_doc = {
            "request_id": inp.request_id,
            "driver_id": inp.driver_id,
            "created_at": now.isoformat(),
            "decision": decision,
            "reasons": [r.code.value for r in reasons],
            "advisories": advisories,
            "stages": stage_view,
            "consent_at": inp.consent_at.isoformat(),
            "consent_policy_version": inp.consent_policy_version,
            "claimed": {
                "full_name": inp.claimed.full_name,
                "date_of_birth": inp.claimed.date_of_birth.isoformat(),
                "licence_number": inp.claimed.licence_number,
                "issuing_province": inp.claimed.issuing_province,
                "plate_number": inp.claimed.plate_number,
                "vehicle_colour": inp.claimed.vehicle_colour,
            },
            "barcode_fields": dict(record.fields) if record else None,
            "timings_ms": timings,
        }
        manifest_id = writer.commit(record_doc)

        timings["total"] = round((time.perf_counter() - t_start) * 1000, 1)
        response = {
            "request_id": inp.request_id,
            "decision": decision,
            "reasons": [{"code": r.code.value, "retryable": r.retryable, "message": r.message} for r in reasons],
            "stages": stage_view,
            "advisories": advisories,
            "timings_ms": timings,
            "rss_mb": round(hardware.rss_mb(), 1),
            "audit": {"manifest_id": manifest_id, "key_id": self._s.manifest_key_id},
        }
        save(self._store, inp.request_id, inp.driver_id, inp.payload_sha256, response)
        return response


def build_engine(settings: Settings, clock: Callable[[], datetime] = _utc_now) -> Engine:
    from .liveness import DevSkipLiveness, OnnxLiveness
    from .registry import ModelRegistry
    from .stages.barcode import run_barcode_stage
    from .stages.face import FaceDetector, embed, run_face_stage
    from .stages.vehicle import allowed_indices, detect_plate, read_plate, run_vehicle_stage

    registry = ModelRegistry(settings.models_dir, settings.models_dir / "models.lock", settings.liveness_model)
    registry.load()
    store = LocalStore(
        settings.storage_root,
        Cipher(base64.b64decode(settings.storage_key_b64.get_secret_value()), settings.storage_key_id),
    )
    detector = FaceDetector(registry.face_detector_path)
    embedder_session = registry.session("face_embedder")
    plate_detector, plate_ocr = registry.session("plate_detector"), registry.session("plate_ocr")
    allowed = allowed_indices(registry.plate_charset)

    if settings.liveness_model is not None:
        liveness: Any = OnnxLiveness(
            registry.session("liveness"),
            settings.liveness_crop_scale,
            settings.liveness_input_size,
            settings.liveness_live_index,
        )
        skipped = False
    elif settings.dev_skip_liveness:
        liveness, skipped = DevSkipLiveness(), True
    else:
        raise EngineError("LIVENESS_MODEL_MISSING")

    stages = Stages(
        barcode=run_barcode_stage,
        face=lambda selfie, front: run_face_stage(
            selfie, front, detector, lambda crop: embed(crop, embedder_session), liveness, settings
        ),
        vehicle=lambda img, claimed: run_vehicle_stage(
            img,
            claimed,
            lambda i: detect_plate(i, plate_detector),
            lambda c: read_plate(c, plate_ocr, registry.plate_charset, allowed),
            settings,
        ),
        liveness_skipped=skipped,
    )
    engine = Engine(settings, store, stages, clock)
    engine.health_info = lambda: {"models_loaded": dict(registry.loaded)}
    return engine
