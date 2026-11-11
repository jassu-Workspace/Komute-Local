"""Shared types. No FastAPI imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal

import numpy as np


class ReasonCode(StrEnum):
    BARCODE_UNREADABLE = "BARCODE_UNREADABLE"
    BARCODE_NOT_AAMVA = "BARCODE_NOT_AAMVA"
    FACE_NOT_FOUND_SELFIE = "FACE_NOT_FOUND_SELFIE"
    FACE_NOT_FOUND_LICENCE = "FACE_NOT_FOUND_LICENCE"
    IMAGE_QUALITY = "IMAGE_QUALITY"
    PLATE_NOT_FOUND = "PLATE_NOT_FOUND"
    PLATE_UNREADABLE = "PLATE_UNREADABLE"
    LIVENESS_FAILED = "LIVENESS_FAILED"
    JURISDICTION_MISMATCH = "JURISDICTION_MISMATCH"
    NAME_MISMATCH = "NAME_MISMATCH"
    DOB_MISMATCH = "DOB_MISMATCH"
    LICENCE_NUMBER_MISMATCH = "LICENCE_NUMBER_MISMATCH"
    LICENCE_EXPIRED = "LICENCE_EXPIRED"
    UNDERAGE = "UNDERAGE"
    FACE_MISMATCH = "FACE_MISMATCH"
    PLATE_MISMATCH = "PLATE_MISMATCH"


_R = ReasonCode

# Spec 2.5: a better photo could change the result.
RETRYABLE: frozenset[ReasonCode] = frozenset({
    _R.BARCODE_UNREADABLE, _R.BARCODE_NOT_AAMVA, _R.FACE_NOT_FOUND_SELFIE,
    _R.FACE_NOT_FOUND_LICENCE, _R.IMAGE_QUALITY, _R.PLATE_NOT_FOUND,
    _R.PLATE_UNREADABLE, _R.LIVENESS_FAILED,
})

MESSAGES: dict[ReasonCode, str] = {
    _R.BARCODE_UNREADABLE: "The barcode on the back of your licence is not clearly visible. Please retake the photo of the barcode.",
    _R.BARCODE_NOT_AAMVA: "The barcode on your licence is not in a supported format. Please photograph the barcode on the back again.",
    _R.FACE_NOT_FOUND_SELFIE: "No face was found in your selfie. Please retake it with your face clearly visible.",
    _R.FACE_NOT_FOUND_LICENCE: "No face was found on the front of your licence. Please retake the photo of the licence front.",
    _R.IMAGE_QUALITY: "An image is too unclear or shows more than one person. Please retake the photo.",
    _R.PLATE_NOT_FOUND: "No licence plate was found in the vehicle photo. Please retake it with the plate clearly visible.",
    _R.PLATE_UNREADABLE: "The licence plate could not be read reliably. Please retake the photo closer to the plate.",
    _R.LIVENESS_FAILED: "The selfie did not pass the live-person check. Please retake it in good light, without a screen or printed photo.",
    _R.JURISDICTION_MISMATCH: "The issuing province does not match the province on the licence barcode.",
    _R.NAME_MISMATCH: "The name given does not match the name on the licence.",
    _R.DOB_MISMATCH: "The date of birth given does not match the licence.",
    _R.LICENCE_NUMBER_MISMATCH: "The licence number given does not match the licence.",
    _R.LICENCE_EXPIRED: "The licence has expired.",
    _R.UNDERAGE: "The licence holder is under the minimum age.",
    _R.FACE_MISMATCH: "The selfie does not match the face on the licence.",
    _R.PLATE_MISMATCH: "The licence plate in the photo does not match the plate given.",
}


@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    retryable: bool
    message: str

    @classmethod
    def of(cls, code: ReasonCode) -> Reason:
        return cls(code, code in RETRYABLE, MESSAGES[code])


class Advisory(StrEnum):
    COLOUR_MISMATCH = "COLOUR_MISMATCH"
    COLOUR_UNVERIFIED = "COLOUR_UNVERIFIED"
    LICENCE_FORMAT_UNUSUAL = "LICENCE_FORMAT_UNUSUAL"
    LIVENESS_SKIPPED_DEV = "LIVENESS_SKIPPED_DEV"


@dataclass(frozen=True)
class Claimed:
    full_name: str
    date_of_birth: date
    licence_number: str
    issuing_province: str
    plate_number: str
    vehicle_colour: str
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None


@dataclass
class StageResult:
    name: Literal["barcode", "face", "vehicle"]
    ran: bool
    reasons: list[Reason] = field(default_factory=list)
    advisories: list[Advisory] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    crops: dict[str, np.ndarray] = field(default_factory=dict)


class InputError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class EngineError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
