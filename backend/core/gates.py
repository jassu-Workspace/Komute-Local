"""Licence gates: compare the barcode record to the claimed data and the policy. Collects every failure."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import policy
from .aamva import AamvaRecord
from .contracts import Advisory, Claimed, Reason, ReasonCode
from .matching import age_on, names_match, normalise_licence


def _safe_province(code: str) -> str | None:
    try:
        return policy.normalise_province(code)
    except ValueError:
        return None


def licence_gates(
    record: AamvaRecord, claimed: Claimed, now_utc: datetime
) -> tuple[list[Reason], list[Advisory]]:
    reasons: list[Reason] = []
    advisories: list[Advisory] = []

    def fail(code: ReasonCode) -> None:
        reasons.append(Reason.of(code))

    claimed_prov = _safe_province(claimed.issuing_province)
    iin_prov = policy.IIN_TO_PROVINCE.get(record.iin)
    daj_prov = _safe_province(record.fields.get("DAJ", ""))
    if not (iin_prov and iin_prov == daj_prov == claimed_prov):
        fail(ReasonCode.JURISDICTION_MISMATCH)
    province = iin_prov or daj_prov or claimed_prov
    if province is None:
        return reasons, advisories  # nothing else can be judged without a province

    barcode_licence = normalise_licence(record.fields.get("DAQ", ""))
    if not barcode_licence or barcode_licence != normalise_licence(claimed.licence_number):
        fail(ReasonCode.LICENCE_NUMBER_MISMATCH)
    if barcode_licence and not policy.LICENCE_PATTERNS[province].match(barcode_licence):
        advisories.append(Advisory.LICENCE_FORMAT_UNUSUAL)

    if not names_match(claimed.full_name, record.full_name())[0]:
        fail(ReasonCode.NAME_MISMATCH)

    dob = record.date("DBB")
    if dob is None or dob != claimed.date_of_birth:
        fail(ReasonCode.DOB_MISMATCH)

    today = now_utc.astimezone(ZoneInfo(policy.TIMEZONES[province])).date()
    expiry = record.date("DBA")
    if expiry is None or today > expiry:
        fail(ReasonCode.LICENCE_EXPIRED)
    if dob is not None and age_on(dob, today) < policy.MIN_AGE:
        fail(ReasonCode.UNDERAGE)

    return reasons, advisories
