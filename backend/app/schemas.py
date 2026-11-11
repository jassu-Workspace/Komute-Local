"""Validate the multipart request into a VerifyInput. Every failure is a specific 422 code."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

from backend.core import policy
from backend.core.contracts import Claimed
from backend.core.imaging import IMAGE_KEYS
from backend.core.pipeline import VerifyInput

from .errors import ApiError

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TEXT_FIELDS = (
    "claimed.full_name", "claimed.licence_number", "claimed.plate_number", "claimed.vehicle_colour",
)
MAX_TEXT = 200  # default; the app passes Settings.max_text_chars


def _bad(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def _text(form: dict[str, str], name: str, max_text: int = MAX_TEXT) -> str:
    value = (form.get(name) or "").strip()
    if not value:
        raise _bad("MISSING_FIELD", f"Field {name} is required.")
    if len(value) > max_text:
        raise _bad("INVALID_FIELD", f"Field {name} is too long.")
    return value


def payload_hash(form: dict[str, str], images: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for k in sorted(form):
        h.update(k.encode() + b"\0" + form[k].encode() + b"\0")
    for k in IMAGE_KEYS:
        h.update(hashlib.sha256(images[k]).digest())
    return h.hexdigest()


def build_input(form: dict[str, str], images: dict[str, bytes], max_text: int = MAX_TEXT) -> VerifyInput:
    request_id, driver_id = (form.get("request_id") or "").strip(), (form.get("driver_id") or "").strip()
    for name, value in (("request_id", request_id), ("driver_id", driver_id)):
        if not value:
            raise _bad("MISSING_FIELD", f"Field {name} is required.")
        if not ID_RE.match(value):
            raise _bad("INVALID_FIELD", f"Field {name} may only contain letters, digits, - and _ (max 64).")

    consent_at, version = (form.get("consent_at") or "").strip(), (form.get("consent_policy_version") or "").strip()
    if not consent_at or not version:
        raise _bad("CONSENT_REQUIRED", "consent_at and consent_policy_version are required.")
    try:
        consent_dt = datetime.fromisoformat(consent_at.replace("Z", "+00:00"))
    except ValueError:
        raise _bad("INVALID_FIELD", "consent_at must be an ISO-8601 timestamp.") from None
    if consent_dt.tzinfo is None:
        raise _bad("INVALID_FIELD", "consent_at must include a time zone.")
    if len(version) > max_text:
        raise _bad("INVALID_FIELD", "consent_policy_version is too long.")

    text = {name: _text(form, name, max_text) for name in TEXT_FIELDS}
    try:
        dob = date.fromisoformat((form.get("claimed.date_of_birth") or "").strip())
    except ValueError:
        raise _bad("INVALID_FIELD", "claimed.date_of_birth must be YYYY-MM-DD.") from None
    try:
        province = policy.normalise_province(form.get("claimed.issuing_province") or "")
    except ValueError:
        raise _bad("INVALID_FIELD", "claimed.issuing_province must be one of the 13 provincial and territorial codes.") from None
    year_raw = (form.get("claimed.vehicle_year") or "").strip()
    if year_raw and not (year_raw.isdigit() and 1900 <= int(year_raw) <= 2100):
        raise _bad("INVALID_FIELD", "claimed.vehicle_year must be a four-digit year.")

    claimed = Claimed(
        full_name=text["claimed.full_name"], date_of_birth=dob, licence_number=text["claimed.licence_number"],
        issuing_province=province, plate_number=text["claimed.plate_number"],
        vehicle_colour=text["claimed.vehicle_colour"],
        vehicle_make=(form.get("claimed.vehicle_make") or "").strip() or None,
        vehicle_model=(form.get("claimed.vehicle_model") or "").strip() or None,
        vehicle_year=int(year_raw) if year_raw else None,
    )
    return VerifyInput(
        request_id, driver_id, consent_dt, version, claimed, images, payload_hash(form, images)
    )
