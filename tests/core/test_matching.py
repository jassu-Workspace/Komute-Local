from datetime import date

import pytest

from backend.core.matching import (
    age_on,
    names_match,
    normalise_licence,
    normalise_name,
    normalise_plate,
    plates_match,
)


def test_accents_hyphens_and_order_ignored():
    ok, score = names_match("Zoë Tremblay-Côté", "TREMBLAY COTE, ZOE")
    assert ok and score == 100.0


def test_middle_name_on_document_only_matches():
    ok, score = names_match("John Smith", "SMITH, JOHN ANDREW")
    assert ok and score == 100.0


def test_middle_name_on_claimed_only_matches():
    assert names_match("John Andrew Smith", "SMITH JOHN")[0]


def test_lone_surname_does_not_match_full_name():
    assert not names_match("Smith", "SMITH, JOHN ANDREW")[0]


def test_different_names_do_not_match():
    ok, score = names_match("Ana Lee", "BOB KHAN")
    assert not ok and score < 50


def test_known_weakness_one_letter_surname_typo_can_pass():
    # Documents the owner's 85% rule: a one-letter surname difference with the same given name passes.
    ok, score = names_match("John Smith", "SMYTH JOHN")
    assert ok and 85 <= score < 100


def test_given_name_typo_with_middle_name_does_not_get_free_pass():
    assert not names_match("Jon Smith", "SMITH, JOHN ANDREW")[0]


def test_empty_names_never_match():
    assert names_match("", "SMITH JOHN") == (False, 0.0)


def test_normalise_name():
    assert normalise_name("  Zoë  O'Neil-Côté ") == "ZOE O NEIL COTE"


def test_normalise_licence_keeps_star_drops_hyphens_spaces():
    assert normalise_licence("a1234-56789-01234") == "A12345678901234"
    assert normalise_licence("pub*i-150290 123") == "PUB*I150290123"


@pytest.mark.parametrize(
    "read,claimed,expected",
    [
        ("ABC1O3", "ABC103", True),
        ("ABC123", "ABK123", False),
        ("ABC 123", "abc-123", True),
        ("AB0O23", "ABOO23", True),
        ("8B0123", "BBO123", False),
        ("", "ABC123", False),
        ("ABC123", "", False),
        ("ABC12", "ABC123", False),
        ("ABCI23", "ABC123", True),
        ("ABC823", "ABCB23", True),
    ],
)
def test_plates(read, claimed, expected):
    assert plates_match(read, claimed) is expected


def test_normalise_plate():
    assert normalise_plate("ab-c 1.23") == "ABC123"


def test_age_on_leap_day_birthday():
    assert age_on(date(2008, 2, 29), date(2026, 2, 28)) == 17
    assert age_on(date(2008, 2, 29), date(2026, 3, 1)) == 18


def test_age_on_birthday_today_and_day_before():
    assert age_on(date(2000, 6, 15), date(2018, 6, 15)) == 18
    assert age_on(date(2000, 6, 15), date(2018, 6, 14)) == 17
