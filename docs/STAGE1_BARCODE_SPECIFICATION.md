# Stage 1 Specification — AAMVA PDF417 Barcode Engine & Parser

> **Deterministic extraction, subfile directory parsing, provincial extension mapping, and Canadian/US date grammar compliance via persistent multi-variant 2D AAMVA PDF417 decoding.**

---

## 1. Overview & Standard Compliance

Stage 1 serves as the primary ground-truth identity extraction engine in Komüte-Local. It eliminates optical character recognition (OCR) ambiguity by decoding the **AAMVA (American Association of Motor Vehicle Administrators) National Standard PDF417 2D barcode** printed on the reverse side of all North American (Canadian and United States) driver's licenses and state/provincial identification cards.

### Core Architectural Advantages Over Optical OCR
* **100% Deterministic Alphanumeric Integrity**: Zero confusion between `O` (letter) and `0` (digit), `I` (letter) and `1` (digit), or `B` and `8`.
* **Zero Halftone/Glare Sensitivity**: Immune to card lamination reflections, micro-print interference, and optical distortion.
* **Provincial & State Standard Compliance**: Adheres to the official AAMVA DL/ID Card Design Standard (versions 1 through 10) and Canadian provincial extensions (e.g., Ontario Ministry of Transportation `ZO` subfiles).
* **Deterministic Subfile Directory Architecture**: Extracts structured metadata from both primary driver license (`DL`) and jurisdiction-specific (`ZO`/`ZV`/`ZJ`) subfile containers.

---

## 2. Authoritative AAMVA Data Dictionary & Segregation Mapping

The AAMVA specification defines standardized 3-character element identifiers. The engine maps these tokens into **6 canonical categories** matching the production dashboard layout:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CANONICAL FIELD GROUPS                          │
├─────────────────┬──────────────────┬─────────────────┬─────────────────┤
│    IDENTITY     │     LICENCE      │      DATES      │     ADDRESS     │
│   (DCS, DAC,    │ (DAQ, DAJ, DCF,  │ (DBA, DBB, DBD, │ (DAG, DAI, DAK, │
│    DAD, ZOA)    │  DCG, DCK, ZOZ)  │    DDB, DDC)    │    DAL, DAM)    │
├─────────────────┴──────────────────┴─────────────────┴─────────────────┤
│                 PHYSICAL           │       CLASS / RESTRICTION         │
│         (DAU, DAY, DBC, DAZ, DCE)  │          (DCA, DCB, DCD)          │
└────────────────────────────────────┴───────────────────────────────────┘
```

### 2.1 Complete Authoritative Element Mapping Table

| Element ID | Category Group | Authoritative Meaning / Description | Canadian / US Format & Usage |
| :--- | :--- | :--- | :--- |
| **`DAQ`** | `LICENCE` | Customer ID / License number | Official license number (e.g., `G62090000000429`) |
| **`DCS`** | `IDENTITY` | Family name (surname) | Primary legal last name (e.g., `SAJIKUMAR`) |
| **`DAC`** | `IDENTITY` | First name | Primary legal given name |
| **`DAD`** | `IDENTITY` | Middle name(s) | Middle name or `NONE` / empty |
| **`DBB`** | `DATES` | Date of birth | 8 digits (`CCYYMMDD` for CAN, `MMDDCCYY` for USA) |
| **`DBA`** | `DATES` | Expiry date | 8 digits (`CCYYMMDD` for CAN, `MMDDCCYY` for USA) |
| **`DBD`** | `DATES` | Issue date | 8 digits (`CCYYMMDD` for CAN, `MMDDCCYY` for USA) |
| **`DBC`** | `PHYSICAL` | Sex (`1`=M, `2`=F, `9`=Unspecified) | Numeric biological sex code per AAMVA |
| **`DAY`** | `PHYSICAL` | Eye color | 3-letter code (`BLK`, `BLU`, `BRO`, `GRY`, `GRN`, `UNK`) |
| **`DAU`** | `PHYSICAL` | Height | Length with unit (e.g., `170 cm` or `068 in`) |
| **`DAG`** | `ADDRESS` | Street address line 1 | Primary street number and name |
| **`DAI`** | `ADDRESS` | City | Municipality or city name |
| **`DAJ`** | `LICENCE` | Jurisdiction code | 2-letter province/state code (e.g., `ON`, `AB`, `BC`, `CA`, `NY`) |
| **`DAK`** | `ADDRESS` | Postal code / ZIP code | Alphanumeric (CAN: `A1A1A1`) or 5/9 digits (US: `12345`) |
| **`DCF`** | `LICENCE` | Document discriminator / audit number | Unique manufacturing/audit tracking number |
| **`DCG`** | `LICENCE` | Country (USA/CAN) | 3-letter country code (`CAN` or `USA`) |
| **`DCK`** | `LICENCE` | Document number / inventory control | Physical stock/inventory tracking string (e.g., `*1462949*`) |
| **`DDE`** | `IDENTITY` | Family name truncation flag | `T` = truncated, `N` = not truncated, `U` = unknown |
| **`DDF`** | `IDENTITY` | First name truncation flag | `T` = truncated, `N` = not truncated, `U` = unknown |
| **`DDG`** | `IDENTITY` | Middle name truncation flag | `T` = truncated, `N` = not truncated, `U` = unknown |
| **`DCA`** | `CLASS / RESTRICTION` | Jurisdiction-specific vehicle class | Operating class (e.g., `G`, `Class 5`, `D`, `A`) |
| **`DCB`** | `CLASS / RESTRICTION` | Jurisdiction-specific restriction codes | Driver restrictions (e.g., corrective lenses, day only) |
| **`DCD`** | `CLASS / RESTRICTION` | Jurisdiction-specific endorsement codes | Special endorsements (e.g., air brakes, motorcycle) |
| **`DCL`** | `PHYSICAL` | Race / ethnicity | Optional demographic code |
| **`DCU`** | `IDENTITY` | Name suffix | Generation suffix (e.g., `JR`, `SR`, `III`) |
| **`DCE`** | `PHYSICAL` | Weight range / description | Weight code or range |
| **`DDA`** | `CLASS / RESTRICTION` | Compliance type | `F` = Full Real-ID, `P` = Partial, `N` = Non-compliant |
| **`DDB`** | `DATES` | Card revision date | Card design revision date (8 digits) |
| **`DDC`** | `DATES` | Hazmat endorsement expiry | Hazardous material qualification expiration date |
| **`DDD`** | `CLASS / RESTRICTION` | Limited duration indicator | `0` = permanent, `1` = temporary/limited duration |
| **`DAZ`** | `PHYSICAL` | Hair color | 3-letter hair color abbreviation |
| **`DBH`** | `PHYSICAL` | Organ donor indicator | `1` = Yes, `0` or empty = No |
| **`DBI`** | `CLASS / RESTRICTION` | Non-resident indicator | Resident status flag |
| **`DBJ`** | `LICENCE` | Unique customer ID | Secondary jurisdiction identification number |
| **`DBK`** | `LICENCE` | Social security number | US licenses only (absent in Canadian jurisdictions) |
| **`PAA`–`PAZ`** | `CLASS / RESTRICTION` | Jurisdiction-specific optional fields | Reserved for custom state/provincial definitions |

### 2.2 Provincial Extensions (Ontario & Maritime Jurisdictions)

Canadian provinces (such as Ontario and Nova Scotia) embed supplementary subfiles beyond the base AAMVA specification:

| Extension Code | Group | Official Meaning | Real-World Payload Example |
| :--- | :--- | :--- | :--- |
| **`ZOA`** | `IDENTITY` | Ontario Reformatted Legal Name | `GOKUL SAJIKUMAR,` |
| **`ZOB`** | `LICENCE` | Ontario Verification Flag | `Y` |
| **`ZOZ`** | `LICENCE` | Ontario 1D Code 39 Cross-Check String | `G6209-00000-00429` |
| **`ZOC`–`ZOE`** | `LICENCE` | Ministry of Transportation Internal Codes | Provincial transit control tokens |
| **`DAH`** | `ADDRESS` | Nova Scotia Municipality Variant | Alternative municipal district |

---

## 3. Date Parsing & International Wire Order Resolution

A critical failure point in standard barcode parsers is misinterpreting 8-digit date strings. The AAMVA standard specifies different wire formats based on the issuing nation:

* **Canada (`DCG == "CAN"`)**: Standardizes on **`CCYYMMDD`** (Century, Year, Month, Day).
* **United States (`DCG == "USA"`)**: Standardizes on **`MMDDCCYY`** (Month, Day, Century, Year).

### 3.1 Date Normalization Algorithm

```python
def date_order(country: Optional[str], value: str) -> Optional[str]:
    # 1. Authoritative check via DCG country code
    if country == "CAN":
        return "CCYYMMDD"
    elif country == "USA":
        return "MMDDCCYY"

    # 2. Heuristic fallback when country code is missing
    digits = (value or "").strip()
    if len(digits) == 8 and digits.isdigit():
        head = int(digits[:4])
        tail = int(digits[4:])
        # If head is a valid year (1900-2099) and tail is not -> CCYYMMDD
        if (1900 <= head <= 2099) and not (1900 <= tail <= 2099):
            return "CCYYMMDD"
        # If tail is a valid year and head is not -> MMDDCCYY
        if (1900 <= tail <= 2099) and not (1900 <= head <= 2099):
            return "MMDDCCYY"
    return None

def format_date(value: str, order: Optional[str]) -> Optional[str]:
    if not value or len(value) != 8 or not value.isdigit():
        return None
    if order == "CCYYMMDD":
        y, m, d = value[0:4], value[4:6], value[6:8]
    elif order == "MMDDCCYY":
        m, d, y = value[0:2], value[2:4], value[4:8]
    else:
        return None
    # ISO-8601 Output Validation
    if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
        return f"{y}-{m}-{d}"
    return None
```

* **Dashboard Dual Representation**: In the production dashboard, dates display the raw wire digits followed by the normalized ISO-8601 date highlighted in emerald green (e.g., `20271231` `2027-12-31`).

---

## 4. AAMVA Header & Subfile Directory Parsing

Real-world driver license barcodes do not contain raw text; they contain a structured binary transport layout:

```
@ <LF> <RS> <CR> ANSI <IIN:6> <Version:2> <JurisdictionVer:2> <Subfiles:2> [Subfile Directory...]
```

```
Byte Offset:   00   01   02   03   04..07   08..13   14..15   16..17   18..19   20..29       30..39
Raw Character: @    \n   \x1e \r   ANSI     636012   09       00       02       DL00410217   ZO02580060
Field:         Lead Control Header IIN      Ver      Juris    Count    Subfile 1    Subfile 2
```

### 4.1 Subfile Directory Parser (`_parse_directory`)

The subfile directory table indicates the exact byte offset and length of each data section:
* **Subfile 1**: Type `DL`, Offset `0041`, Length `0217` bytes.
* **Subfile 2**: Type `ZO`, Offset `0258`, Length `0060` bytes.

```python
def parse_aamva(text: str) -> Optional[dict]:
    text = _normalize_hri(text)
    raw = text
    probe = text.replace("\x1e", "").replace("\x00", "").strip()

    if not (probe.startswith("@") and ("ANSI" in probe[:64] or "AAMVA" in probe[:128])):
        return None

    iin, version, designators = _parse_directory(text)
    fields = {}

    for subfile_type, offset, length in designators:
        if length <= 0 or offset < 0:
            continue
        body = raw[offset : offset + length]
        if len(body) < 3:
            continue
        # Strip repeated 2-character subfile prefix ("DL...", "ZO...")
        if body.startswith(subfile_type):
            body = body[2:]
        fields.update(_scan_elements(body))

    if not fields:
        # Fallback to linear scan if directory table is corrupted
        fields = _scan_elements(probe)

    return {
        "issuer": iin,
        "version": version,
        "fields": fields,
        "raw": text
    }
```

### 4.2 Raw Control Code Annotation

To facilitate human verification and auditing, control characters are converted into visible, standardized tags:
* `\n` $\rightarrow$ `<LF>` (Line Feed, `0x0A`)
* `\r` $\rightarrow$ `<CR>` (Carriage Return, `0x0D`)
* `\x1e` $\rightarrow$ `<RS>` (Record Separator, `0x1E`)
* `\x1d` $\rightarrow$ `<GS>` (Group Separator, `0x1D`)

Example Annotated Output:
```
@<LF><RS><CR>ANSI 636012090002DL00410217ZO02580060DLDCAG<LF>DCB<LF>DCD<LF>DBA20271231<LF>DCSGOKUL SAJIKUMAR<LF>...
```

---

## 5. Persistent Multi-Variant Scanning Engine

Smartphone photos of license cards frequently suffer from perspective tilt, low illumination, vertical capture orientation, or superficial 1D barcodes on the card surface (e.g., Code 128 inventory tracking numbers).

The engine executes an intelligent **19-variant search pipeline** using `zxing-cpp`:

```
                           Raw Card Back Photo
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │             _generate_variants() [19 Passes]            │
       ├─────────────────────────────────────────────────────────┤
       │ 1. Base Image (Exif Orientation Corrected)              │
       │ 2. Scaled Canvas 1.6x (Lanczos Interpolation)           │
       │ 3. Scaled Canvas 2.5x (High-Density Module Resolution)  │
       │ 4. Autocontrast + Sharpness Enhancement (2.0x)          │
       │ 5. Big Sharpened 1.6x                                   │
       │ 6. Otsu Adaptive Binarization                           │
       │ 7. Scaled Otsu Binarization (1.8x)                      │
       │ 8. Inverted Grayscale (Dark Card Theme)                 │
       │ 9. Inverted Autocontrast                                │
       │ 10. Rotated -90° (Vertical Phone Capture Correction)    │
       │ 11. Rotated +90° (Vertical Inverted Capture Correction) │
       │ 12-15. Quadrant Crops (Top-L, Top-R, Bot-L, Bot-R)     │
       │ 16-17. Horizontal Stripe Crops (Top Half, Bottom Half)  │
       │ 18-19. Scaled Crops (2.0x on high-likelihood regions)   │
       └─────────────────────────────────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │              _scan_strategies() Evaluation              │
       ├─────────────────────────────────────────────────────────┤
       │ Pass A: Binarizer.LocalAverage (is_pure = False)        │
       │ Pass B: Binarizer.GlobalHistogram (is_pure = True)      │
       │ Pass C: Binarizer.GlobalHistogram (is_pure = False)     │
       │ Pass D: Binarizer.LocalAverage (is_pure = True)         │
       └─────────────────────────────────────────────────────────┘
                                    │
                                    ▼
       [Persistent Filter]: Continues scanning until PDF417 is
       found, preventing early termination on 1D barcodes.
```

---

## 6. Real-Time Memory Dynamics & Profiling Analysis

During benchmark profiling on Windows/Linux environments, Stage 1 exhibits a distinctive memory profile:

| Metric | Measured Value | Architectural Reason |
| :--- | :--- | :--- |
| **RAM Baseline** | **346.45 MB** | CPython runtime + loaded OpenCV DLLs + ONNX Runtime engine. |
| **Peak Sampled RAM** | **853.63 MB** | Up to 19 uncompressed bitmap images in RAM + native C++ `BitMatrix` buffers. |
| **Microsecond Surge** | **+507.18 MB** | Peak allocation spike during multi-variant generation ($2.5\times$ upscaling). |
| **Stage Net Delta** | **388.48 MB** | Committed virtual memory pages retained by the OS/CRT heap allocator. |
| **Stage 1 Total Latency** | **~90 to 1970 ms** | 19 passes evaluated sequentially until the PDF417 symbol is located. |

### Technical Cause of the +507 MB Surge
1. **Uncompressed Bitmap Buffers**: An uncompressed $1845 \times 1924$ photo scaled to $2.5\times$ creates a $4612 \times 4810 \times 3\text{ byte}$ buffer ($\approx \mathbf{66.5\text{ MB}}$ per single image). Pre-computing 19 variations consumes $\sim 350\text{ MB}$ of Python heap memory.
2. **Native C++ Raster Pyramid**: `zxing-cpp` allocates native image pyramid tiers and 2D `BitMatrix` threshold grids during `LocalAverage` passes ($\sim 150\text{ MB}$).
3. **OS Heap Retention**: The Windows C-Runtime (`ucrtbase.dll` / Low Fragmentation Heap) marks freed memory as reusable rather than releasing the physical pages back to the Windows kernel. This pre-allocates the working set for subsequent stages (Stage 2 and 3 exhibit negligible memory growth as a result).

---

## 7. JSON Output Specification & Contracts

The output of Stage 1 is serialized into both the master benchmark JSON (`benchmark_results.json`) and the dashboard clipboard payload:

```json
{
  "stage": "Stage 1: AAMVA Barcode Decoder",
  "executed": true,
  "latency_ms": 91.74,
  "barcode_detected": true,
  "format": "PDF417",
  "issuer_iin": "636012",
  "aamva_version": "09",
  "image_metadata": {
    "width": 1200,
    "height": 1600,
    "scans": 19
  },
  "flat_fields": {
    "DAQ": "G62090000000429",
    "DCS": "SAJIKUMAR",
    "DAC": "GOKUL",
    "DBA": "20271231",
    "DBB": "20000429",
    "DBD": "20230914",
    "DCG": "CAN",
    "DAJ": "ON",
    "DAG": "91 WEBER ST S",
    "DAI": "WATERLOO",
    "DAK": "N2J2A2",
    "DAU": "170 cm",
    "DAY": "UNK",
    "DBC": "1",
    "DCA": "G",
    "DCF": "HV8996268",
    "DCK": "*1462949*",
    "DDE": "N",
    "DDF": "N",
    "DDG": "N",
    "ZOA": "GOKUL SAJIKUMAR,",
    "ZOB": "Y",
    "ZOZ": "G6209-00000-00429"
  },
  "categorized_fields": {
    "IDENTITY": [
      {"id": "DCS", "meaning": "Family name (surname)", "raw_value": "SAJIKUMAR", "formatted_date": null},
      {"id": "DDE", "meaning": "Family name truncation flag", "raw_value": "N", "formatted_date": null},
      {"id": "DDF", "meaning": "First name truncation flag", "raw_value": "N", "formatted_date": null},
      {"id": "DDG", "meaning": "Middle name truncation flag", "raw_value": "N", "formatted_date": null},
      {"id": "ZOA", "meaning": "ON ZO reformatted name", "raw_value": "GOKUL SAJIKUMAR,", "formatted_date": null}
    ],
    "LICENCE": [
      {"id": "DAJ", "meaning": "Jurisdiction code (2-letter province)", "raw_value": "ON", "formatted_date": null},
      {"id": "DAQ", "meaning": "Customer ID / License number", "raw_value": "G62090000000429", "formatted_date": null},
      {"id": "DCF", "meaning": "Document discriminator / audit number", "raw_value": "HV8996268", "formatted_date": null},
      {"id": "DCG", "meaning": "Country (USA/CAN)", "raw_value": "CAN", "formatted_date": null},
      {"id": "DCK", "meaning": "Document number / inventory control", "raw_value": "*1462949*", "formatted_date": null},
      {"id": "ZOB", "meaning": "ON ZO flag", "raw_value": "Y", "formatted_date": null},
      {"id": "ZOZ", "meaning": "ON ZO check number (= 1D Code39)", "raw_value": "G6209-00000-00429", "formatted_date": null}
    ],
    "DATES": [
      {"id": "DBA", "meaning": "Expiry date (CCYYMMDD)", "raw_value": "20271231", "formatted_date": "2027-12-31"},
      {"id": "DBB", "meaning": "Date of birth (CCYYMMDD)", "raw_value": "20000429", "formatted_date": "2000-04-29"},
      {"id": "DBD", "meaning": "Issue date (CCYYMMDD)", "raw_value": "20230914", "formatted_date": "2023-09-14"}
    ],
    "ADDRESS": [
      {"id": "DAG", "meaning": "Street address line 1", "raw_value": "91 WEBER ST S", "formatted_date": null},
      {"id": "DAI", "meaning": "City", "raw_value": "WATERLOO", "formatted_date": null},
      {"id": "DAK", "meaning": "Postal code", "raw_value": "N2J2A2", "formatted_date": null}
    ],
    "PHYSICAL": [
      {"id": "DAU", "meaning": "Height (cm)", "raw_value": "170 cm", "formatted_date": null},
      {"id": "DAY", "meaning": "Eye color", "raw_value": "UNK", "formatted_date": null},
      {"id": "DBC", "meaning": "Sex (1=M, 2=F)", "raw_value": "1", "formatted_date": null}
    ],
    "CLASS / RESTRICTION": [
      {"id": "DCA", "meaning": "Jurisdiction-specific vehicle class", "raw_value": "G", "formatted_date": null}
    ]
  },
  "micro_latencies": {
    "zxing_scan_decode_ms": 86.914,
    "aamva_token_parsing_ms": 0.252
  },
  "memory": {
    "ram_start_mb": 346.45,
    "ram_peak_mb": 853.63,
    "ram_surge_mb": 507.18,
    "ram_delta_mb": 388.48
  },
  "status": "PASSED"
}
```
