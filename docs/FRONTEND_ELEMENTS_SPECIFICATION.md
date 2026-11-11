# Frontend Elements Specification — Komüte-Local Verifier

> **Comprehensive functional inventory of all required frontend elements, input contracts, specimen dropzones, telemetry displays, and outcome presentation structures derived from the reference node.**

---

## 1. Overview & Architectural Role

The frontend layer serves as the operator and applicant interaction workbench for Komüte-Local. Its role is strictly to:
1. Ingest applicant credentials and physical image specimens.
2. Formulate and dispatch the structured verification request payload.
3. Present the binary decision outcome (`APPROVED`, `REJECTED`, or `DEGRADED`), stage-by-stage evaluation metrics, isolated facial crops, and raw audit proofs.

> **Design Independence Guarantee**: The frontend is completely decoupled from the core processing engine. The backend functions autonomously via headless CLI and API calls regardless of whether the frontend folder is present.

---

## 2. Authentication & Node Access Elements

These elements manage operator authentication state when communicating with secured verification endpoints.

| Element Identifier | Functional Component | Input / Display Type | Functional Behavior & Data Contract |
| :--- | :--- | :--- | :--- |
| **`apiKeyInput`** | Operator Secret Key Input | Password / Masked Text | Captures the operator API key. Retained securely in `sessionStorage` (`kmt_api_key`) across sessions. Transmitted via the `X-API-Key` HTTP header. |
| **`authBadge`** | Authentication State Badge | Status Container | Visual container reflecting current node access state. |
| **`authIndicator`** | Connection Status Dot | Binary State Indicator | Dynamic status beacon: active when key is verified, warning when key is required, error when invalid. |
| **`authBadgeText`** | Status Text Label | Text Display | Displays active authentication state: `AUTHENTICATED`, `KEY REQUIRED`, `INVALID KEY`, or `NO AUTH REQUIRED`. |
| **`authModal`** | Access Challenge Modal | Overlay Container | Intercepts submissions when authentication is enabled on the server but no key is present in memory. |
| **`modalApiKeyInput`** | Modal Key Entry Field | Password Input | Captures operator key from within the modal prompt and auto-focuses on trigger. |
| **`authKeyHintSpan`** | Key Hint Subtext | Text Display | Displays optional non-sensitive server key hint (e.g., prefix or environment identifier). |

---

## 3. Applicant & Driver Credential Form Elements

These elements capture the applicant's claimed identity and vehicle data to establish the ground truth for automated matching.

| Element Identifier | Field Name | Element Type | Data Contract & Validation |
| :--- | :--- | :--- | :--- |
| **`fullName`** | Full Legal Name | Text Input | Applicant's official full legal name (First, Middle, Last). Required. Compared against extracted license text and AAMVA barcode fields (`DAC`, `DAD`, `DCS`). |
| **`issuingProvince`** | Issuing Jurisdiction | Dropdown Select | 2-letter Canadian provincial or territorial code: `ON`, `AB`, `BC`, `QC`, `MB`, `SK`, `NS`, `NB`, `NL`, `PE`, `NT`, `YT`, `NU`. Required. Determines provincial grammar rules. |
| **`dlNumber`** | Driver License Number | Text Input | Official jurisdiction license string. Required. Compared against barcode field `DAQ`. |
| **`dlHintRow`** | Grammar Hint Container | Information Bar | Contextual feedback container dynamically updated on province change. |
| **`dlHintDesc`** | Format Grammar Description | Dynamic Text | Displays active jurisdiction rule (e.g., *"1 letter + 14 digits"* for ON, *"7 digits"* for AB/BC). |
| **`dlCharCounter`** | Live Character Counter | Counter Display | Displays real-time length tracking (e.g., `0 / 15 chars`). |
| **`dob`** | Date of Birth | Date Picker (`YYYY-MM-DD`) | Driver claimed date of birth. Required. Verified against barcode field `DBB` to enforce driver age gates ($\ge 18.0$ years). |
| **`expiryDate`** | License Expiry Date | Date Picker (`YYYY-MM-DD`) | Document expiration date. Required. Compared against barcode field `DBA` to enforce active validity gates. |
| **`plateNumber`** | Vehicle License Plate | Text Input | Vehicle registration plate string. Required. Cleaned of spaces/hyphens and compared against ALPR OCR results. |
| **`vehColor`** | Vehicle Body Color | Text Input | Claimed exterior paint color (e.g., `Black`, `White`, `Grey`, `Blue`, `Red`). Compared against CIELAB $\Delta E$ classified body color. |

---

## 4. Specimen Ingestion & Preview Elements

Four dedicated dropzones handle image file ingestion, local base64 serialization, drag-and-drop events, and specimen previews.

| Zone Identifier | Input Identifier | Specimen Role | Ingestion Status & Preview Elements |
| :--- | :--- | :--- | :--- |
| **`selfieZone`** | **`selfieInput`** | Live Selfie Portrait | **`selfieLabel`**: Displays ingestion state (*"Awaiting Upload"* $\rightarrow$ *"Specimen Loaded"*).<br>**`selfieThumb`**: Displays scaled thumbnail preview of the captured live portrait. Used for Stage 2 face verification and liveness checks. |
| **`dlZone`** | **`dlInput`** | License Card Front | **`dlLabel`**: Displays card front ingestion state.<br>**`dlThumb`**: Displays front card thumbnail. Used for Stage 2A facial portrait cropping and 5-point landmark isolation. |
| **`dlBackZone`** | **`dlBackInput`** | License Card Back (Barcode) | **`dlBackLabel`**: Displays card back ingestion state.<br>**`dlBackThumb`**: Displays card back thumbnail. Designated as *Optional but Recommended* (primary deterministic AAMVA PDF417 verification path). |
| **`vehZone`** | **`vehInput`** | Vehicle Exterior Photo | **`vehLabel`**: Displays vehicle photo ingestion state.<br>**`vehThumb`**: Displays vehicle exterior thumbnail. Used for Stage 3A plate detection, Stage 3B OCR, and Stage 3C sheet-metal paint color classification. |

---

## 5. Execution & Control Elements

| Element Identifier | Control Element | Functional Trigger |
| :--- | :--- | :--- |
| **`submitBtn`** | Pipeline Evaluation Button | Validates presence of mandatory specimens, serializes the JSON request payload with base64 images, transitions to loading state (*"EVALUATING PIPELINE..."* with progress spinner), and dispatches `POST /api/v1/verify`. |
| **`clearForm`** | Workbench Reset Button | Purges all form input values, clears base64 image buffers in memory, resets specimen labels and thumbnail previews, and restores the results panel to its empty state. |

---

## 6. Decision Outcome & Telemetry Elements

These elements render the composite verdict, execution timings, and issue diagnostics.

| Element Identifier | Display Element | Data Mapping & Presentation Behavior |
| :--- | :--- | :--- |
| **`resultsCard`** | Results Panel Container | Master container wrapping all verification telemetry. Hidden until execution completes. |
| **`emptyState`** | Awaiting Verification State | Placeholder container displayed prior to specimen submission. |
| **`resultContent`** | Active Results Wrapper | Displays the rendered outcome once a verification response is received. |
| **`latencySpan`** | Execution Timer Display | Displays total end-to-end processing latency in milliseconds (e.g., `138.4 ms execution`). |
| **`outcomeBanner`** | Primary Verdict Card | Primary decision banner with distinct operational states: `outcome-approved` (Green), `outcome-rejected` (Red), or `outcome-degraded` (Amber). |
| **`outcomeStatus`** | Decision Text | Prominently displays the binary decision: **`APPROVED`**, **`REJECTED`**, or **`DEGRADED`**. |
| **`outcomeSub`** | Verdict Explanation | Subtext providing high-level rationale (e.g., *"All gate thresholds satisfied"* or *"Verification requirements not satisfied"*). |
| **`compositeScore`** | Composite Confidence Metric | Formatted numeric percentage display (e.g., `94.2%`) representing the weighted composite score. |
| **`reasonsBanner`** | Rejection Issue Container | Collapsible alert container displayed when rejection triggers are present. |
| **`reasonsList`** | Rejection Diagnostic Items | Bulleted list rendering specific hard rejection triggers (e.g., underage driver, expired license, facial biometric mismatch). |
| **`degradedBanner`** | Subsystem Degradation Banner | Alert container displayed when downstream dependencies fail or operate in degraded fallback modes. |
| **`degradedList`** | Degraded Subsystem Items | Itemized list detailing affected services, failure reasons, and fallback providers. |

---

## 7. Stage-by-Stage Verification Telemetry Panels

Each processing stage provides granular field-level verification metrics.

### 7.1 Stage 1: License Data & Barcode Verification Panel
* **`s1Badge`**: Status badge displaying `PASS` or `FAIL`.
* **`s1TableContainer`**: Rendered key-value table displaying:
  * Extracted Driver License Number (`extracted_dl_number`)
  * License Number Match Ratio (`number_similarity`)
  * Legal Name Match Ratio (`name_similarity`)
  * License Expiry Verification Boolean (`is_expired`)
  * Minimum Driver Age Verification Boolean (`driver_age_valid`)
  * Verification Source (`AAMVA_PDF417_BARCODE` or OCR fallback)
  * Structured AAMVA Fields: `IDENTITY`, `LICENCE`, `DATES`, `ADDRESS`, `PHYSICAL`, `CLASS / RESTRICTION`.

### 7.2 Stage 2: Biometrics & Facial Identity Panel
* **`s2Badge`**: Status badge displaying `PASS` or `FAIL`.
* **`s2TableContainer`**: Rendered key-value table displaying:
  * Identity Match Verdict (`is_match`: `MATCH_CONFIRMED` or `REJECTED_MISMATCH`)
  * Facial Cosine Similarity Metric (`confidence_score`)
  * Calibrated Cross-Age Threshold (`calibrated_threshold`, standard `0.40`)
  * Liveness Verification Boolean (`is_live`)
  * Continuous Chronological Age Delta (`estimated_age_delta_years`)
  * Live Selfie Estimated Age (`selfie_estimated_age`)
  * License Portrait Estimated Age (`id_estimated_age`)
* **Dual Aligned Facial Crops**:
  * **`selfieCrop`**: Display frame presenting the isolated, aligned live selfie face.
  * **`dlCrop`**: Display frame presenting the privacy-sanitized face crop isolated from the license card.
* **`s2Desc`**: Explanatory caption detailing biometric consistency across the chronological age gap.

### 7.3 Stage 3: Vehicle Verification & ALPR Panel
* **`s3Badge`**: Status badge displaying `PASS` or `FAIL`.
* **`s3TableContainer`**: Rendered key-value table displaying:
  * Extracted License Plate String (`extracted_plate`)
  * Plate Alphanumeric Similarity Ratio (`plate_similarity`)
  * Plate Match Boolean (`plate_matched`)
  * Vehicle Exterior Color Match Boolean (`color_matched`)
  * Detected Body Paint Color Name (`detected_color`)
  * Color Swatch & Hex Code (`color_hex`)
  * CIELAB Color Distance Metric (`cielab_delta_e`)

---

## 8. Cryptographic Proof & Raw Audit Elements

* **`toggleArrow`**: Interactive toggle glyph controlling visibility of the raw telemetry payload.
* **`rawBox`**: Scrollable, formatted JSON viewer displaying the complete, immutable response payload for audit compliance, record keeping, and automated integration testing.
