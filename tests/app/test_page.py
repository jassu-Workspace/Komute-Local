import re
from pathlib import Path

from backend.core.imaging import IMAGE_KEYS

PAGE = Path("backend/static/index.html")
HTML = PAGE.read_text(encoding="utf-8")

FIELD_NAMES = [
    "request_id", "driver_id", "consent_at", "consent_policy_version", "claimed.full_name", "claimed.date_of_birth",
    "claimed.licence_number", "claimed.issuing_province", "claimed.plate_number", "claimed.vehicle_colour",
    "claimed.vehicle_make", "claimed.vehicle_model", *IMAGE_KEYS,
]


def test_page_has_no_external_urls():
    assert "http://" not in HTML and "https://" not in HTML
    assert not re.search(r"<(script|link)[^>]+(src|href)=", HTML)


def test_page_has_all_contract_fields():
    for name in FIELD_NAMES:
        assert f'name="{name}"' in HTML, name


def test_page_posts_to_verify_with_api_key_header():
    assert 'fetch("/v1/verify"' in HTML and "X-API-Key" in HTML


def test_page_uses_textcontent_not_innerhtml():
    assert "innerHTML" not in HTML and "document.write" not in HTML and "eval(" not in HTML


def test_every_input_has_a_label():
    ids = re.findall(r'<(?:input|select)[^>]*\bid="([^"]+)"', HTML)
    assert ids
    for i in ids:
        assert f'for="{i}"' in HTML, i


def test_page_is_responsive_and_storage_is_guarded():
    assert 'name="viewport"' in HTML
    assert re.search(r"try\s*\{[^}]*sessionStorage", HTML)
    assert re.search(r"all 13|\"ON\",\"QC\",\"BC\",\"AB\",\"MB\",\"SK\",\"NB\",\"NS\",\"NL\",\"PE\",\"YT\",\"NT\",\"NU\"", HTML)


STATS = Path("backend/static/stats.html").read_text(encoding="utf-8")


def test_stats_page_is_self_contained_and_safe():
    assert "http://" not in STATS and "https://" not in STATS
    assert not re.search(r"<(script|link)[^>]+(src|href)=", STATS)
    assert "innerHTML" not in STATS and "document.write" not in STATS and "eval(" not in STATS
    assert 'fetch("/v1/system"' in STATS and "X-API-Key" in STATS and 'name="viewport"' in STATS
    assert re.search(r"try\s*\{[^}]*sessionStorage", STATS)
