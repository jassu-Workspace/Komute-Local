# Stage 1: Licence barcode and gates

Decodes the AAMVA PDF417 on the licence back, parses it, and runs the licence gates. The barcode is the ground truth. Code: `backend/core/stages/barcode.py`, `aamva.py`, `gates.py`, `policy.py`.

## Decoding (`decode_pdf417`)

- Converts to grayscale once. Builds image variants **one at a time** and frees each before building the next, then stops at the first PDF417 hit. Order: original, 1.6×, 2.5×, sharpened, CLAHE, Otsu, 1.8× Otsu, inverted, ±90° rotations, four quadrants, top and bottom halves, 2× half crops. Variants over 25 megapixels are skipped.
- Each variant is read with zxing-cpp (`PDF417` only) under two binarisers. 1D barcodes on the card are ignored.
- A wall-clock budget (default 10 s) ends the search. A blank or barcode-free photo returns `None` in 2–6 s on the test machine.
- An unreadable barcode gives `BARCODE_UNREADABLE` (retryable): "The barcode on the back of your licence is not clearly visible. Please retake the photo of the barcode." There is no OCR fallback.

## Parsing (`parse_aamva`)

- Header: `@` + control bytes + `ANSI ` or `AAMVA`, IIN (6 digits), version (2). Versions 02 and above add a 2-digit jurisdiction version before the entry count.
- Subfile directory: type (2), offset (4), length (4) per entry. Elements are 3 uppercase letters plus a value up to a line break.
- **Real-card quirk:** a Saskatchewan card writes offset `0000`. The parser finds the subfile by its type marker after the directory instead of trusting the offset.
- A linear scan is the last fallback. A PDF417 that is not AAMVA gives `BARCODE_NOT_AAMVA` (retryable).
- Dates follow `DCG`: `CAN` is `CCYYMMDD`, `USA` is `MMDDCCYY`. Without `DCG`, a heuristic decides. Invalid dates parse to `None`.
- **Name** is taken from the first source that exists: `DAC`+`DAD`+`DCS`, then `DCT`+`DCS`, `DAA`, `ZOA` (Ontario cards leave `DAC` empty), then `DCS` alone (some issuers store the whole name there).

## Gates (`licence_gates`). Every failure is collected.

| Gate | Rule | Code (final unless noted) |
|---|---|---|
| Jurisdiction | claimed province = province of the IIN = province in `DAJ` (`NF` counts as `NL`) | `JURISDICTION_MISMATCH` |
| Licence number | barcode `DAQ` equals the claimed number after removing everything but `A–Z`, `0–9`, `*`. The owner's regex is an advisory only | `LICENCE_NUMBER_MISMATCH` (advisory `LICENCE_FORMAT_UNUSUAL`) |
| Name | accents and punctuation removed, token-sort match ≥ 85, or every claimed token appears exactly in the barcode name (≥ 2 tokens) | `NAME_MISMATCH` |
| Date of birth | exact match to `DBB` | `DOB_MISMATCH` |
| Expiry | valid through the end of `DBA` in the issuing province's time zone | `LICENCE_EXPIRED` |
| Age | 18 or older on that local date, from the barcode date of birth | `UNDERAGE` |

Any class and any restriction code is accepted in every province. Only age 18+ and an unexpired licence decide eligibility.

Any Stage 1 failure stops the pipeline: Stages 2 and 3 do not run.
