import pytest

from backend.core import policy


def test_iin_table_has_13_entries_matching_claude_md():
    assert len(policy.IIN_TO_PROVINCE) == 13
    assert set(policy.IIN_TO_PROVINCE.values()) == set(policy.PROVINCES)
    claude = open("CLAUDE.md", encoding="utf-8").read()
    for iin, prov in policy.IIN_TO_PROVINCE.items():
        assert f"| {prov} |" in claude and iin in claude


def test_every_province_has_pattern_and_timezone():
    for p in policy.PROVINCES:
        assert p in policy.LICENCE_PATTERNS and p in policy.TIMEZONES


def test_nf_normalises_to_nl_and_junk_raises():
    assert policy.normalise_province("nf") == "NL"
    assert policy.normalise_province(" on ") == "ON"
    for bad in ("", "XX", "NEWFOUNDLAND", None):
        with pytest.raises(ValueError):
            policy.normalise_province(bad)


def test_owner_patterns_accept_owner_examples():
    assert policy.LICENCE_PATTERNS["ON"].match("A12345678901234")
    assert policy.LICENCE_PATTERNS["NS"].match("PUBLI150290123")
    assert policy.LICENCE_PATTERNS["MB"].match("PUBLIJQ123AB")
    assert not policy.LICENCE_PATTERNS["SK"].match("1234567")
