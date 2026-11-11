from datetime import date, datetime, timezone

from backend.core.aamva import parse_aamva
from backend.core.contracts import Advisory, Claimed, ReasonCode
from backend.core.gates import licence_gates
from tests.fixtures.aamva_factory import FAKE_FIELDS, make_aamva_text

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)


def claimed(**kw) -> Claimed:
    base = dict(
        full_name="Alex Jamie Tester", date_of_birth=date(1990, 3, 15),
        licence_number="T1234-56789-01234", issuing_province="ON", plate_number="ABC123",
        vehicle_colour="Grey", vehicle_make=None, vehicle_model=None, vehicle_year=None,
    )
    base.update(kw)
    return Claimed(**base)


def run(fields=None, iin="636012", cl=None, now=NOW):
    rec = parse_aamva(make_aamva_text(iin=iin, fields=dict(FAKE_FIELDS, **(fields or {}))))
    reasons, adv = licence_gates(rec, cl or claimed(), now)
    return {r.code for r in reasons}, adv


def test_all_pass_for_valid_ontario_g():
    assert run()[0] == set()


def test_g2_rejected_class():
    assert ReasonCode.CLASS_NOT_ALLOWED in run({"DCA": "G2"})[0]


def test_expiry_today_passes_and_yesterday_fails():
    assert ReasonCode.LICENCE_EXPIRED not in run({"DBA": "20261111"})[0]
    assert ReasonCode.LICENCE_EXPIRED in run({"DBA": "20261110"})[0]


def test_vancouver_midnight_boundary():
    # 2026-06-02 02:00Z is still 1 June in Vancouver, so a licence expiring on 1 June is valid.
    f = {"DAJ": "BC", "DCA": "5", "DAQ": "1234567", "DBA": "20260601"}
    cl = claimed(issuing_province="BC", licence_number="1234567")
    early = datetime(2026, 6, 2, 2, 0, tzinfo=timezone.utc)
    late = datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)
    assert ReasonCode.LICENCE_EXPIRED not in run(f, iin="636028", cl=cl, now=early)[0]
    assert ReasonCode.LICENCE_EXPIRED in run(f, iin="636028", cl=cl, now=late)[0]


def test_underage_17():
    codes, _ = run({"DBB": "20090315"}, cl=claimed(date_of_birth=date(2009, 3, 15)))
    assert ReasonCode.UNDERAGE in codes


def test_exactly_18_today_passes():
    codes, _ = run({"DBB": "20081111"}, cl=claimed(date_of_birth=date(2008, 11, 11)))
    assert ReasonCode.UNDERAGE not in codes


def test_unknown_restriction_fails_closed():
    assert ReasonCode.RESTRICTION_UNKNOWN in run({"DCB": "ZZ"})[0]
    assert ReasonCode.RESTRICTION_UNKNOWN not in run({"DCB": "NONE"})[0]
    assert ReasonCode.RESTRICTION_UNKNOWN not in run({"DCB": ""})[0]


def test_quebec_class_5_ok():
    f = {"DAJ": "QC", "DCA": "5", "DAQ": "T123456789012"}
    cl = claimed(issuing_province="QC", licence_number="T123456789012")
    assert run(f, iin="604428", cl=cl)[0] == set()


def test_manitoba_empty_class_table_fails_closed():
    f = {"DAJ": "MB", "DCA": "5", "DAQ": "PUBLIJQ123AB"}
    cl = claimed(issuing_province="MB", licence_number="PUBLIJQ123AB")
    assert ReasonCode.CLASS_NOT_ALLOWED in run(f, iin="636048", cl=cl)[0]


def test_dob_mismatch_by_one_day():
    assert ReasonCode.DOB_MISMATCH in run(cl=claimed(date_of_birth=date(1990, 3, 16)))[0]


def test_collects_multiple_failures():
    codes, _ = run({"DCA": "G1", "DBA": "20200101"}, cl=claimed(full_name="Somebody Else"))
    assert {ReasonCode.CLASS_NOT_ALLOWED, ReasonCode.LICENCE_EXPIRED, ReasonCode.NAME_MISMATCH} <= codes


def test_jurisdiction_mismatch_between_claim_iin_and_daj():
    assert ReasonCode.JURISDICTION_MISMATCH in run(cl=claimed(issuing_province="QC"))[0]
    assert ReasonCode.JURISDICTION_MISMATCH in run({"DAJ": "QC"})[0]
    assert ReasonCode.JURISDICTION_MISMATCH in run(iin="999999")[0]


def test_nf_in_daj_accepted_for_newfoundland():
    f = {"DAJ": "NF", "DAQ": "T123456789", "DCA": "5"}
    cl = claimed(issuing_province="NL", licence_number="T123456789")
    assert ReasonCode.JURISDICTION_MISMATCH not in run(f, iin="636016", cl=cl)[0]


def test_licence_number_mismatch_and_unusual_format_advisory():
    codes, adv = run({"DAQ": "123"}, cl=claimed(licence_number="123"))
    assert ReasonCode.LICENCE_NUMBER_MISMATCH not in codes
    assert Advisory.LICENCE_FORMAT_UNUSUAL in adv
    assert ReasonCode.LICENCE_NUMBER_MISMATCH in run(cl=claimed(licence_number="T99999999999999"))[0]


def test_missing_dates_fail_closed():
    f = {k: v for k, v in FAKE_FIELDS.items() if k not in ("DBA", "DBB")}
    rec = parse_aamva(make_aamva_text(fields=f))
    codes = {r.code for r in licence_gates(rec, claimed(), NOW)[0]}
    assert {ReasonCode.LICENCE_EXPIRED, ReasonCode.DOB_MISMATCH} <= codes
    assert ReasonCode.UNDERAGE not in codes


def test_unparseable_claimed_province_does_not_crash():
    assert ReasonCode.JURISDICTION_MISMATCH in run(cl=claimed(issuing_province="ZZ"))[0]
