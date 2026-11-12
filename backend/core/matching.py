"""Pure matching helpers: names, licence numbers, plates, age. No I/O."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from rapidfuzz import fuzz

CONFUSION_PAIRS = frozenset({frozenset("O0"), frozenset("I1"), frozenset("B8")})


def normalise_name(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]", " ", stripped.upper()).split())


def names_match(claimed: str, document: str, threshold: float = 90.0) -> tuple[bool, float]:
    a, b = normalise_name(claimed), normalise_name(document)
    if not a or not b:
        return False, 0.0
    score = float(fuzz.token_sort_ratio(a, b))
    if score >= threshold:
        return True, score
    # A middle name on one side only: every token of the shorter name appears exactly in the longer.
    # Needs at least two tokens, so a lone surname never matches. No fuzziness: typos gain nothing.
    ta, tb = set(a.split()), set(b.split())
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 2 and small <= large:
        return True, 100.0
    return False, score


def normalise_licence(s: str) -> str:
    return re.sub(r"[^A-Z0-9*]", "", s.upper())


def normalise_plate(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def plates_match(read: str, claimed: str) -> bool:
    a, b = normalise_plate(read), normalise_plate(claimed)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) != len(b):
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diffs) == 1 and frozenset(diffs[0]) in CONFUSION_PAIRS


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
