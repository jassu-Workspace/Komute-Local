"""AAMVA PDF417 text parser: header, subfile directory, data elements, dates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

_HEADER = re.compile(r"^@[\n\r\x1e]{0,4}(?:ANSI |AAMVA)(\d{6})(\d{2})")
_ELEMENT = re.compile(r"^[A-Z]{3}$")
_FIRST_ELEMENT = re.compile(r"(?:DL|ID|ZO|ZV|ZJ|ZA|ZB|ZC)([A-Z]{3}.*)$")
_SEPARATORS = re.compile(r"[\n\r]")

DateOrder = Literal["CCYYMMDD", "MMDDCCYY"]


def date_order(country: Optional[str], value: str) -> Optional[DateOrder]:
    if country == "CAN":
        return "CCYYMMDD"
    if country == "USA":
        return "MMDDCCYY"
    digits = (value or "").strip()
    if len(digits) == 8 and digits.isdigit():
        head, tail = int(digits[:4]), int(digits[4:])
        head_year, tail_year = 1900 <= head <= 2099, 1900 <= tail <= 2099
        if head_year and not tail_year:
            return "CCYYMMDD"
        if tail_year and not head_year:
            return "MMDDCCYY"
    return None


def parse_date(value: str, order: Optional[DateOrder]) -> Optional[date]:
    value = (value or "").strip()
    if order is None or len(value) != 8 or not value.isdigit():
        return None
    if order == "CCYYMMDD":
        y, m, d = int(value[0:4]), int(value[4:6]), int(value[6:8])
    else:
        m, d, y = int(value[0:2]), int(value[2:4]), int(value[4:8])
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _scan_elements(body: str, first_line_has_header: bool = False) -> dict[str, str]:
    fields: dict[str, str] = {}
    for i, line in enumerate(_SEPARATORS.split(body)):
        if i == 0 and first_line_has_header:
            m = _FIRST_ELEMENT.search(line)
            if not m:
                continue
            line = m.group(1)
        if len(line) >= 3 and _ELEMENT.match(line[:3]):
            fields[line[:3]] = line[3:].strip()
    return fields


def _parse_directory(text: str, pos: int, version: int) -> Optional[dict[str, str]]:
    if version >= 2:
        pos += 2  # jurisdiction version
    count_txt = text[pos : pos + 2]
    if not count_txt.isdigit():
        return None
    pos += 2
    fields: dict[str, str] = {}
    for _ in range(int(count_txt)):
        entry = text[pos : pos + 10]
        if len(entry) < 10 or not entry[2:].isdigit():
            return None
        sub_type, offset, length = entry[:2], int(entry[2:6]), int(entry[6:10])
        pos += 10
        body = text[offset : offset + length]
        if len(body) < 3:
            return None
        if body.startswith(sub_type):
            body = body[2:]
        fields.update(_scan_elements(body))
    return fields or None


@dataclass(frozen=True)
class AamvaRecord:
    iin: str
    version: str
    fields: dict[str, str]

    def country(self) -> Optional[str]:
        return self.fields.get("DCG") or None

    def date(self, element: str) -> Optional[date]:
        value = self.fields.get(element, "")
        return parse_date(value, date_order(self.country(), value))

    def full_name(self) -> str:
        f = self.fields
        if f.get("DAC") and f.get("DCS"):
            middle = f.get("DAD", "")
            parts = [f["DAC"], "" if middle.upper() == "NONE" else middle, f["DCS"]]
        elif f.get("DCT") and f.get("DCS"):
            parts = [f["DCT"], f["DCS"]]
        else:
            parts = [f.get("DAA", "")]
        return " ".join(" ".join(parts).replace(",", " ").split())


def parse_aamva(text: str) -> Optional[AamvaRecord]:
    if not isinstance(text, str):
        return None
    m = _HEADER.match(text)
    if not m:
        return None
    iin, version = m.group(1), m.group(2)
    fields = _parse_directory(text, m.end(), int(version))
    if not fields:
        fields = _scan_elements(text[m.end() :], first_line_has_header=True)
    if not fields:
        return None
    return AamvaRecord(iin=iin, version=version, fields=fields)
