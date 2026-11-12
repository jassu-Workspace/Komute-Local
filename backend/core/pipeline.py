"""The verification engine: ingest, stages, decision, audit. Fails closed: a fault is an error, never a decision."""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import cv2
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
from .monitor import EngineMonitor

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


def _shrink(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return img
    return cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)


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
        self.models_info: Callable[[], list[dict]] = lambda: []
        self.monitor = EngineMonitor()

    @property
    def store(self) -> BlobStore:
        return self._store

    def verify(self, inp: VerifyInput) -> dict:
        cached = lookup(self._store, inp.request_id, inp.payload_sha256)  # may raise IdempotencyConflict
        if cached is not None:
            return cached
        self.monitor.begin()
        try:
            return self._run(inp)
        except (InputError, IdempotencyConflict):
            self.monitor.abandon()
            raise
        except Exception as e:  # the one fail-closed boundary: any fault is an error, never a decision
            self.monitor.failed()
            log.error("engine fault request_id=%s type=%s", inp.request_id, type(e).__name__)
            raise EngineError("ENGINE_ERROR") from e
        finally:
            hardware.trim_heap()

    def _run(self, inp: VerifyInput) -> dict:
        with hardware.MemorySampler() as mem:
            return self._run_sampled(inp, mem)

    def _run_sampled(self, inp: VerifyInput, mem: hardware.MemorySampler) -> dict:
        t_start = time.perf_counter()
        now = self._clock()
        images = {k: decode_image(inp.image_bytes[k], self._s.max_image_side) for k in IMAGE_KEYS}

        mem.mark("decoded")
        self.monitor.stage("store")
        prefix = session_prefix(inp.driver_id, inp.request_id)
        self._store.delete_prefix(prefix)  # a retry starts clean: leftovers of a crashed run are never trusted
        writer = SessionWriter(self._store, prefix, self._manifest_key, self._s.manifest_key_id, now)
        for k in IMAGE_KEYS:
            writer.put(f"originals/{k}.{_ext(inp.image_bytes[k])}", inp.image_bytes[k])

        mem.mark("stored")
        self.monitor.stage("barcode")
        barcode, record = self._stages.barcode(images["licence_back"], inp.claimed, now)
        mem.mark("barcode")
        if barcode.reasons:
            face, vehicle = _skipped("face"), _skipped("vehicle")
        else:
            self.monitor.stage("face")
            face = self._stages.face(images["selfie"], images["licence_front"])
            mem.mark("face")
            self.monitor.stage("vehicle")
            vehicle = self._stages.vehicle(images["vehicle"], inp.claimed)
            mem.mark("vehicle")
        results = [barcode, face, vehicle]
        self.monitor.stage("audit")

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
            writer.put(
                f"compressed/{k}.webp",
                encode_webp(_shrink(images[k], self._s.compressed_max_side), COMPRESS_QUALITY[k]),
            )

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
                "licence_class": inp.claimed.licence_class,
                "issue_date": inp.claimed.issue_date.isoformat() if inp.claimed.issue_date else None,
                "expiry_date": inp.claimed.expiry_date.isoformat() if inp.claimed.expiry_date else None,
            },
            "barcode_fields": dict(record.fields) if record else None,
            "timings_ms": timings,
        }
        manifest_id = writer.commit(record_doc)

        timings["total"] = round((time.perf_counter() - t_start) * 1000, 1)
        mem.mark("saved")
        response = {
            "request_id": inp.request_id,
            "decision": decision,
            "reasons": [{"code": r.code.value, "retryable": r.retryable, "message": r.message} for r in reasons],
            "stages": stage_view,
            "advisories": advisories,
            "timings_ms": timings,
            "rss_mb": round(hardware.rss_mb(), 1),
            "memory_trace": mem.trace(),
            "audit": {"manifest_id": manifest_id, "key_id": self._s.manifest_key_id},
        }
        if self._s.response_barcode_fields and record is not None:
            response["barcode_fields"] = dict(record.fields)
        save(self._store, inp.request_id, inp.driver_id, inp.payload_sha256, response)
        self.monitor.done(response, {f"{r.name}.{k}": v for r in results for k, v in r.timings_ms.items()})
        return response


def _warm_up(detector, embedder_session, plate_detector, plate_ocr) -> None:
    """One blank inference per model, so the first real request does not pay the ONNX start-up cost."""
    import numpy as np

    from .stages.face import embed
    from .stages.vehicle import detect_plate, read_plate

    t = time.perf_counter()
    try:
        detector.detect(np.zeros((480, 640, 3), np.uint8))
        embed(np.zeros((112, 112, 3), np.uint8), embedder_session)
        detect_plate(np.zeros((480, 640, 3), np.uint8), plate_detector)
        read_plate(np.zeros((64, 128, 3), np.uint8), plate_ocr)
        log.info("models warmed in %.0f ms, rss %.0f MB", (time.perf_counter() - t) * 1000, hardware.rss_mb())
    except Exception as e:  # warm-up is an optimisation; a failure must not stop the node
        log.warning("model warm-up skipped type=%s", type(e).__name__)


def build_engine(settings: Settings, clock: Callable[[], datetime] = _utc_now) -> Engine:
    from .liveness import DevSkipLiveness, OnnxLiveness
    from .registry import ModelRegistry
    from .stages.barcode import run_barcode_stage
    from .stages.face import FaceDetector, embed, run_face_stage
    from .stages.vehicle import detect_plate, read_plate, run_vehicle_stage

    registry = ModelRegistry(settings.models_dir, settings.models_dir / "models.lock", settings.liveness_model)
    registry.load()
    store = LocalStore(
        settings.storage_root,
        Cipher(base64.b64decode(settings.storage_key_b64.get_secret_value()), settings.storage_key_id),
    )
    detector = FaceDetector(registry.face_detector_path, settings.face_detect_score)
    embedder_session = registry.session("face_embedder")
    plate_detector, plate_ocr = registry.session("plate_detector"), registry.session("plate_ocr")

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
        barcode=lambda back, claimed, now: run_barcode_stage(
            back, claimed, now, settings.barcode_budget_s, settings.name_match_threshold, settings.min_age
        ),
        face=lambda selfie, front: run_face_stage(
            selfie, front, detector, lambda crop: embed(crop, embedder_session), liveness, settings
        ),
        vehicle=lambda img, claimed: run_vehicle_stage(
            img,
            claimed,
            lambda i: detect_plate(i, plate_detector, settings.plate_detect_score),
            lambda c: read_plate(c, plate_ocr),
            settings,
        ),
        liveness_skipped=skipped,
    )
    if settings.warmup_max_rss_mb > 0 and hardware.rss_mb() < settings.warmup_max_rss_mb:
        _warm_up(detector, embedder_session, plate_detector, plate_ocr)
    engine = Engine(settings, store, stages, clock)
    engine.health_info = lambda: {"models_loaded": dict(registry.loaded)}
    engine.models_info = registry.describe
    return engine
