"""Per-jurisdiction policy tables. Any class and any restriction are accepted."""
from __future__ import annotations

import re

MIN_AGE = 18

PROVINCES = ("ON", "QC", "BC", "AB", "MB", "SK", "NB", "NS", "NL", "PE", "YT", "NT", "NU")

IIN_TO_PROVINCE = {
    "636012": "ON", "604428": "QC", "636028": "BC", "604432": "AB", "636048": "MB",
    "636044": "SK", "636017": "NB", "636013": "NS", "636016": "NL", "604426": "PE",
    "604429": "YT", "604434": "NT", "604433": "NU",
}

# The owner's patterns. A sanity check only: the barcode licence number is authoritative.
LICENCE_PATTERNS = {
    "ON": re.compile(r"^[A-Z]\d{14}$"),
    "QC": re.compile(r"^[A-Z]\d{12}$"),
    "BC": re.compile(r"^\d{7,8}$"),
    "AB": re.compile(r"^(?:\d{6,9}|[A-Z]{1,2}\d{4,5})$"),
    "MB": re.compile(r"^(?:[A-Z][A-Z*]{4}[A-Z][A-Z*][A-Z0-9]{5,6}|[A-Z]\d{12,13})$"),
    "SK": re.compile(r"^\d{8}$"),
    "NB": re.compile(r"^\d{1,7}$"),
    "NS": re.compile(r"^[A-Z][A-Z* ]{4}\d{9}$"),
    "NL": re.compile(r"^[A-Z]\d{9}$"),
    "PE": re.compile(r"^\d{1,6}$"),
    "YT": re.compile(r"^\d{1,6}$"),
    "NT": re.compile(r"^\d{5,9}$"),
    "NU": re.compile(r"^\d{5,6}$"),
}

TIMEZONES = {
    "ON": "America/Toronto", "QC": "America/Toronto", "BC": "America/Vancouver",
    "AB": "America/Edmonton", "MB": "America/Winnipeg", "SK": "America/Regina",
    "NB": "America/Moncton", "NS": "America/Halifax", "NL": "America/St_Johns",
    "PE": "America/Halifax", "YT": "America/Whitehorse", "NT": "America/Edmonton",
    "NU": "America/Iqaluit",
}

def normalise_province(code: str) -> str:
    c = (code or "").strip().upper()
    if c == "NF":
        c = "NL"
    if c not in PROVINCES:
        raise ValueError(f"unknown province: {code!r}")
    return c
