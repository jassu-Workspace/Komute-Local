"""Build AAMVA barcode text for tests. All values are fake."""
from __future__ import annotations

FAKE_FIELDS = {
    "DCA": "G",
    "DCB": "NONE",
    "DCD": "NONE",
    "DBA": "20301231",
    "DCS": "TESTER",
    "DAC": "ALEX",
    "DAD": "JAMIE",
    "DBD": "20230914",
    "DBB": "19900315",
    "DBC": "1",
    "DAY": "BRO",
    "DAU": "175 cm",
    "DAG": "1 TEST ST",
    "DAI": "TOWN",
    "DAJ": "ON",
    "DAK": "A1A1A1",
    "DAQ": "T12345678901234",
    "DCF": "FAKE0001",
    "DCG": "CAN",
}


def make_aamva_text(
    iin: str = "636012",
    version: str = "09",
    fields: dict[str, str] | None = None,
    extra_subfiles: dict[str, dict[str, str]] | None = None,
) -> str:
    fields = dict(FAKE_FIELDS if fields is None else fields)
    subfiles = [("DL", fields)] + list((extra_subfiles or {}).items())
    bodies = [t + "".join(f"{k}{v}\n" for k, v in f.items()) + "\r" for t, f in subfiles]
    juris = "00" if int(version) >= 2 else ""
    header_len = len("@\n\x1e\rANSI ") + 6 + 2 + len(juris) + 2 + 10 * len(subfiles)
    directory, offset = "", header_len
    for (t, _), body in zip(subfiles, bodies):
        directory += f"{t}{offset:04d}{len(body):04d}"
        offset += len(body)
    return f"@\n\x1e\rANSI {iin}{version}{juris}{len(subfiles):02d}{directory}" + "".join(bodies)
