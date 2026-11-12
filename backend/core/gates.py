"""Licence gates: compare the barcode record to the claimed data and the policy. Collects every failure.

Each cross-checked field also yields a check row (claimed value, decoded value, match score 0-100, pass mark).
Rows hold personal data: they go to the caller and the sealed record, never to logs or the monitor.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import policy
from .aamva import AamvaRecord
from .contracts import Advisory, Claimed, Reason, ReasonCode
from .matching import age_on, names_match, normalise_licence

DEFAULT_NAME_THRESHOLD = 90.0


def _safe_province(code: str) -> str | None:
    try:
        return policy.normalise_province(code)
    except ValueError:
        return None


def normalise_class(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def licence_gates(
    record: AamvaRecord, claimed: Claimed, now_utc: datetime,
    name_threshold: float = DEFAULT_NAME_THRESHOLD, min_age: int = policy.MIN_AGE,
) -> tuple[list[Reason], list[Advisory], list[dict]]:
    reasons: list[Reason] = []
    advisories: list[Advisory] = []
    checks: list[dict] = []

    def fail(code: ReasonCode) -> None:
        reasons.append(Reason.of(code))

    def check(field: str, claimed_v, decoded_v, passed: bool, score: float | None = None,
              threshold: float = 100.0) -> bool:
        checks.append({"field": field, "claimed": claimed_v, "decoded": decoded_v,
                       "score": round(score if score is not None else (100.0 if passed else 0.0), 1),
                       "threshold": threshold, "passed": passed})
        return passed

    claimed_prov = _safe_province(claimed.issuing_province)
    iin_prov = policy.IIN_TO_PROVINCE.get(record.iin)
    daj_prov = _safe_province(record.fields.get("DAJ", ""))
    if not check("issuing_province", claimed_prov, daj_prov or iin_prov,
                 bool(iin_prov and iin_prov == daj_prov == claimed_prov)):
        fail(ReasonCode.JURISDICTION_MISMATCH)
    province = iin_prov or daj_prov or claimed_prov
    if province is None:
        return reasons, advisories, checks  # nothing else can be judged without a province

    barcode_licence = normalise_licence(record.fields.get("DAQ", ""))
    if not check("licence_number", claimed.licence_number, record.fields.get("DAQ") or None,
                 bool(barcode_licence) and barcode_licence == normalise_licence(claimed.licence_number)):
        fail(ReasonCode.LICENCE_NUMBER_MISMATCH)
    if barcode_licence and not policy.LICENCE_PATTERNS[province].match(barcode_licence):
        advisories.append(Advisory.LICENCE_FORMAT_UNUSUAL)

    doc_name = record.full_name()
    ok, score = names_match(claimed.full_name, doc_name, name_threshold)
    if not check("full_name", claimed.full_name, doc_name or None, ok, score, name_threshold):
        fail(ReasonCode.NAME_MISMATCH)

    dob = record.date("DBB")
    if not check("date_of_birth", _iso(claimed.date_of_birth), _iso(dob), dob is not None and dob == claimed.date_of_birth):
        fail(ReasonCode.DOB_MISMATCH)

    doc_class = normalise_class(record.fields.get("DCA"))
    if not check("licence_class", claimed.licence_class, record.fields.get("DCA") or None,
                 bool(doc_class) and doc_class == normalise_class(claimed.licence_class)):
        fail(ReasonCode.CLASS_MISMATCH)

    issued = record.date("DBD")
    if not check("issue_date", _iso(claimed.issue_date), _iso(issued), issued is not None and issued == claimed.issue_date):
        fail(ReasonCode.ISSUE_DATE_MISMATCH)

    expiry = record.date("DBA")
    if not check("expiry_date", _iso(claimed.expiry_date), _iso(expiry), expiry is not None and expiry == claimed.expiry_date):
        fail(ReasonCode.EXPIRY_DATE_MISMATCH)

    today = now_utc.astimezone(ZoneInfo(policy.TIMEZONES[province])).date()
    if expiry is None or today > expiry:
        fail(ReasonCode.LICENCE_EXPIRED)
    if issued is not None and issued > today:
        fail(ReasonCode.LICENCE_NOT_YET_VALID)
    if dob is not None and age_on(dob, today) < min_age:
        fail(ReasonCode.UNDERAGE)

    return reasons, advisories, checks
