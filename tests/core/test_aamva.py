from datetime import date

from backend.core.aamva import date_order, parse_aamva, parse_date
from tests.fixtures.aamva_factory import FAKE_FIELDS, make_aamva_text


def test_ontario_style_card_with_provincial_subfile():
    text = make_aamva_text(extra_subfiles={"ZO": {"ZOA": "ALEX TESTER,", "ZOB": "Y"}})
    rec = parse_aamva(text)
    assert rec.iin == "636012" and rec.version == "09"
    assert rec.fields["DAQ"] == FAKE_FIELDS["DAQ"]
    assert rec.fields["ZOA"] == "ALEX TESTER,"
    assert rec.date("DBB") == date(1990, 3, 15)
    assert rec.date("DBA") == date(2030, 12, 31)


def test_us_date_order():
    f = dict(FAKE_FIELDS, DCG="USA", DBB="03151990", DBA="12312030")
    rec = parse_aamva(make_aamva_text(iin="636001", fields=f))
    assert rec.date("DBB") == date(1990, 3, 15)


def test_missing_dcg_uses_heuristic():
    f = {k: v for k, v in FAKE_FIELDS.items() if k != "DCG"}
    assert parse_aamva(make_aamva_text(fields=f)).date("DBB") == date(1990, 3, 15)
    f2 = dict(f, DBB="03151990")
    assert parse_aamva(make_aamva_text(fields=f2)).date("DBB") == date(1990, 3, 15)


def test_version_01_header_without_jurisdiction_version():
    rec = parse_aamva(make_aamva_text(version="01"))
    assert rec.version == "01" and rec.fields["DAQ"] == FAKE_FIELDS["DAQ"]


def test_name_from_given_middle_surname():
    assert parse_aamva(make_aamva_text()).full_name() == "ALEX JAMIE TESTER"


def test_name_with_none_middle_dropped():
    rec = parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DAD="NONE")))
    assert rec.full_name() == "ALEX TESTER"


def test_name_from_daa_with_commas():
    f = {k: v for k, v in FAKE_FIELDS.items() if k not in ("DAC", "DAD", "DCS")}
    f["DAA"] = "TESTER,ALEX,J"
    name = parse_aamva(make_aamva_text(fields=f)).full_name()
    assert name.split() == ["TESTER", "ALEX", "J"]


def test_name_from_dct():
    f = {k: v for k, v in FAKE_FIELDS.items() if k not in ("DAC", "DAD")}
    f["DCT"] = "ALEX,JAMIE"
    assert parse_aamva(make_aamva_text(fields=f)).full_name() == "ALEX JAMIE TESTER"


def test_corrupt_directory_falls_back_to_linear_scan():
    text = make_aamva_text()
    # break the offset digits of the subfile directory entry
    broken = text.replace("DL00", "DLXX", 1)
    rec = parse_aamva(broken)
    assert rec is not None and rec.fields["DAQ"] == FAKE_FIELDS["DAQ"]


def test_non_aamva_returns_none():
    assert parse_aamva("hello world") is None
    assert parse_aamva("") is None
    assert parse_aamva(None) is None
    assert parse_aamva("@\n\x1e\rANSI 63601209") is None


def test_invalid_date_returns_none():
    rec = parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DBB="19901301")))
    assert rec.date("DBB") is None
    assert parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DBB="1990"))).date("DBB") is None


def test_leap_day_date():
    rec = parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DBB="20080229")))
    assert rec.date("DBB") == date(2008, 2, 29)
    assert parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DBB="20090229"))).date("DBB") is None


def test_date_helpers():
    assert date_order("CAN", "x") == "CCYYMMDD" and date_order("USA", "x") == "MMDDCCYY"
    assert date_order(None, "20000429") == "CCYYMMDD"
    assert date_order(None, "04292000") == "MMDDCCYY"
    assert date_order(None, "20002000") is None
    assert parse_date("20000429", None) is None


def test_empty_restriction_value_kept_as_empty_string():
    rec = parse_aamva(make_aamva_text(fields=dict(FAKE_FIELDS, DCB="")))
    assert rec.fields["DCB"] == ""
