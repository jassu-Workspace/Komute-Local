# Komüte-Local Verification Module: Design Spec

Date: 2026-11-11
Status: **Draft for owner review. Nothing is built.**
Source of truth for decisions: `CLAUDE.md`. This spec turns those decisions into a buildable design.

## 1. Goal

A backend module that a host application calls to decide, with no human in the loop, whether a driver and vehicle pass onboarding. The result is `APPROVED` or `REJECTED`. It runs on CPU in a container with a 1.0–1.3 GB RAM budget. It serves 13 Canadian jurisdictions.

**Success means:** every gate below passes with evidence, not with opinion (see section 11).

**Non-goals:** rate limiting, tenants, billing, dashboards, manual review, OCR of the licence front, licence front-to-back cross-check, make/model recognition, suspension or revocation lookup.

## 2. Public contract

### 2.1 Request: `POST /v1/verify` (multipart)

| Field | Type | Notes |
|---|---|---|
| `request_id` | string | Idempotency key. 1–64 chars, `[A-Za-z0-9_-]`. |
| `driver_id` | string | Same character rules. |
| `consent_at` | ISO-8601 UTC | Required. When the driver gave biometric consent. |
| `consent_policy_version` | string | Required. |
| `claimed.full_name` | string | |
| `claimed.date_of_birth` | `YYYY-MM-DD` | |
| `claimed.licence_number` | string | Hyphens and spaces allowed. Normalised by the engine. |
| `claimed.issuing_province` | enum | `ON QC BC AB MB SK NB NS NL PE YT NT NU`. `NF` is accepted and normalised to `NL`. |
| `claimed.plate_number` | string | |
| `claimed.vehicle_colour` | string | Advisory only. |
| `claimed.vehicle_make/model/year` | string/string/int | Optional. Stored, never checked. |
| `selfie`, `licence_front`, `licence_back`, `vehicle` | image files | JPEG, PNG or WebP. Per-file size limit from config. |

Header `X-API-Key` is required.

### 2.2 Response (HTTP 200 when a decision was made)

```json
{
  "request_id": "REQ-1",
  "decision": "REJECTED",
  "reasons": [
    {"code": "BARCODE_UNREADABLE", "retryable": true,
     "message": "The barcode on the back of your licence is not clearly visible. Please retake the photo of the barcode."}
  ],
  "stages": {
    "barcode": {"ran": true, "readable": false},
    "face": {"ran": false},
    "vehicle": {"ran": false}
  },
  "advisories": [],
  "timings_ms": {"total": 412.3, "barcode": 398.1},
  "rss_mb": 702.4,
  "audit": {"manifest_id": "...", "key_id": "k1"}
}
```

The response carries match results and scores, not the extracted personal data. Raw barcode fields go only into the sealed audit record.

### 2.3 Status codes: decisions versus errors

| Situation | Response |
|---|---|
| Decision made (either outcome) | `200` with `decision` |
| Bad input: missing field, missing consent, unsupported image, oversize | `422` with error code. No decision. |
| Wrong or missing API key | `401` |
| Engine already running a verification | `503` with `Retry-After`. No decision. |
| `request_id` reused with a different payload | `409` |
| `request_id` reused with the same payload | `200` with the stored result. The engine does not run again. |
| Model failed to load, stage crashed, storage failed | `500` with error code. **Never a decision, never `APPROVED`.** |

### 2.4 Other endpoints

`GET /health` (models loaded, RSS, free disk), `GET /v1/sessions/{request_id}` (stored result, same key), `GET /` (the single HTML test page).

### 2.5 Reason codes

Retryable means a better photo could change the result.

| Code | Retryable |
|---|---|
| `BARCODE_UNREADABLE`, `BARCODE_NOT_AAMVA` | yes |
| `FACE_NOT_FOUND_SELFIE`, `FACE_NOT_FOUND_LICENCE`, `IMAGE_QUALITY`, `PLATE_NOT_FOUND`, `PLATE_UNREADABLE` | yes |
| `LIVENESS_FAILED` | yes |
| `JURISDICTION_MISMATCH`, `NAME_MISMATCH`, `DOB_MISMATCH`, `LICENCE_NUMBER_MISMATCH` | no |
| `LICENCE_EXPIRED`, `UNDERAGE`, `CLASS_NOT_ALLOWED`, `RESTRICTION_NOT_ALLOWED`, `RESTRICTION_UNKNOWN` | no |
| `FACE_MISMATCH`, `PLATE_MISMATCH` | no |

## 3. Package layout

```text
backend/
  core/                    # engine. No FastAPI imports. Usable as a library.
    config.py              # typed settings from environment; thresholds; limits
    hardware.py            # thread clamps, ONNX session options, RSS probe
    registry.py            # model loading, SHA-256 check against models.lock
    imaging.py             # decode, EXIF rotate, size cap
    pipeline.py            # orchestrator: ingest -> stages -> decision -> audit
    decision.py            # gates, reason codes, retryable flags
    policy.py              # per-jurisdiction tables: IIN, licence regex, classes, restrictions
    matching.py            # name, plate, date helpers
    audit.py               # session record, manifest, HMAC signing
    stages/
      barcode.py           # variants, zxing-cpp decode, AAMVA parse
      face.py              # YuNet, alignment, liveness, embedding, cosine
      vehicle.py           # plate detect, OCR, colour
  app/                     # thin REST wrapper
    main.py  routes.py  schemas.py  security.py  gate.py   # gate = busy lock, 503
  models/                  # ONNX files + models.lock
  static/index.html        # one file: HTML, inline CSS, inline script
storage/                   # existing module, refactored behind an interface
  base.py  local.py  retention.py  crypto.py
tests/
```

The existing `storage/storage_manager.py` is refactored, not rewritten from scratch. Its path sanitiser is kept. Its import-time side effects are removed.

## 4. Data flow

1. **Gate.** Try to take the single run lock. If taken, return `503`.
2. **Validate.** Check fields, API key, consent. Hash the payload. Look up `request_id` for idempotency.
3. **Ingest.** Decode each image, apply EXIF rotation, cap the long side to the configured maximum. Write originals to storage (encrypted, atomic).
4. **Stage 1, barcode.** Decode the licence back. If unreadable, return `BARCODE_UNREADABLE` and stop. Parse AAMVA. Run the gates in this order: jurisdiction (claimed province = IIN province = `DAJ`), licence number, name, date of birth, expiry, age 18+, class, restrictions. Collect every failed gate. If any failed, stop.
5. **Stage 2, face.** Detect the selfie face and the licence-front face. Run liveness on the selfie. Align both faces and compute embeddings. Compare by cosine similarity.
6. **Stage 3, vehicle.** Detect the plate, read it, apply the plate rule. Classify body colour. Colour mismatch adds an advisory only.
7. **Decide.** `APPROVED` only if no gate failed in any stage that ran and all three stages ran.
8. **Audit.** Write crops and compressed images. Write the session record. Sign the manifest. Store the result under `request_id`.
9. **Release.** Free large buffers, trim the allocator, release the run lock.

Stages 2 and 3 are independent of each other. Both run when Stage 1 passes, and all of their failures are reported together so the driver can fix everything in one retry.

## 5. Stage designs

**Stage 1, barcode.**
- Generate image variants lazily, one at a time, and stop at the first PDF417 hit. Variants: original, 1.6× and 2.5× scale, sharpen, Otsu binarise, invert, ±90° rotation, crops. Free each variant before building the next.
- Use `zxing-cpp` for decoding. Ignore 1D barcodes and keep scanning.
- Parse the header, then the subfile directory, with a linear-scan fallback. Resolve date order by `DCG`.
- `policy.py` holds the 13 IINs, the `NF`/`NL` alias, the class table and the restriction table. The class and restriction tables stay empty for nine jurisdictions until the owner's real samples arrive. An unknown class or restriction code fails closed.

**Stage 2, face.**
- YuNet gives five landmarks. A similarity transform aligns to 112×112.
- Liveness is a small passive anti-spoof model plus cheap screen and print signals. It is single-frame, so it has limits, and the audit record states them.
- The embedding comes from `w600k_r50`. The decision uses a cosine threshold read from config. The provisional value 0.40 is replaced by a value calibrated on data.
- No age estimation (dropped by default).

**Stage 3, vehicle.**
- YOLOv9-tiny at 384×384 finds the plate. OCR output is masked to `A–Z` and `0–9` and decoded with greedy CTC.
- Plate rule: equal after normalisation, or different only by optical-confusion pairs (`O/0`, `I/1`, `B/8`). Anything else is `PLATE_MISMATCH`.
- Colour uses patches next to the plate, CIELAB ΔE against a reference palette. A mismatch adds an advisory only.

## 6. Memory plan

Figures are estimates. The first milestone measures them.

| Item | Budget |
|---|---|
| Python, OpenCV, ONNX Runtime, FastAPI | ~300 MB |
| Resident models (YuNet, face embedding, plate detector, plate OCR, liveness) | ~350 MB |
| Working set for one request (capped images, one barcode variant, tensors) | ≤ 300 MB |
| **Steady-state target** | **≤ 900 MB** |
| **Peak target** | **≤ 1.2 GB** |

Controls: one request at a time, a size cap at decode, lazy barcode variants, a small ONNX arena, and `malloc_trim` after each request on Linux. A test drives 50 sequential requests and fails if RSS grows by more than a set margin.

## 7. Storage design

```text
{root}/sessions/{driver_id}/{request_id}/
  originals/   selfie.jpg licence_front.jpg licence_back.jpg vehicle.jpg
  cropped/     selfie_face.webp licence_face.webp plate.webp
  compressed/  selfie.webp licence_front.webp licence_back.webp vehicle.webp
  record.json  # sealed audit record: decision, reasons, scores, extracted barcode fields, consent, timings
  manifest.json
```

- **Interface.** The pipeline uses `put(path, bytes)`, `get`, `delete_prefix`, `list`. `local.py` implements it on disk. An S3-compatible implementation can follow later without touching the engine.
- **Atomic writes.** Write into `{request_id}.tmp/`, then rename to the final name. A crash never leaves a half session.
- **Encryption.** AES-256-GCM per file. The data key comes from the host's key service through an environment variable or sidecar. The manifest records `key_id`. This needs the `cryptography` package, because the Python standard library has no AES. TLS 1.3 is terminated at the host's proxy.
- **Manifest.** SHA-256 of every file, plus the HMAC-SHA256 signature over the manifest and the record. The signing key is a separate host-injected key with its own `key_id`.
- **Retention.** A sweeper runs at startup and every hour inside the process. Rejected sessions: delete all images after 72 hours. Approved sessions: delete originals after 30 days. `record.json` and `manifest.json` stay (image-free for rejected sessions). Approved manifests stay for tenure plus 7 years, deleted by the host's lifecycle rules.
- **Idempotency index.** One small JSON per `request_id` holds the payload hash and the stored response.

## 8. Error handling

- Every stage returns data, not exceptions, for expected outcomes (no face, no plate, unreadable barcode).
- Unexpected exceptions become a `500` with an error code and are logged with the `request_id`. No partial decision is returned.
- Model files are verified against `models.lock` at startup. A mismatch stops startup.
- If storage fails after a decision, return `500`. Do not return a decision that has no audit record.
- Logs never contain image bytes, names or licence numbers.

## 9. The test page

`static/index.html`: one file, inline CSS, inline script. A form for the claimed fields, four file inputs, an API key box, a submit button, and a result area showing the decision, reasons and timings, with the raw JSON in a collapsible block. No framework. No build step. No external requests.

## 10. Testing strategy

1. **Unit tests.** Date order, name matching, plate rule, licence regexes, policy tables, reason-code logic, manifest signing, path sanitising.
2. **Stage 1 tests.** Generate synthetic AAMVA PDF417 barcodes for all 13 IINs, then apply blur, tilt, rotation and low light. Assert decode and parse results.
3. **Golden samples.** Real licence, selfie and vehicle photos from the owner, kept outside the repo and loaded from a path in an environment variable.
4. **Memory test.** 50 sequential requests, with an RSS bound.
5. **Concurrency test.** A second request during a run returns `503`.
6. **Failure tests.** Corrupt model, full disk, bad key, killed process mid-write.
7. **Calibration harness.** A script that reads a labelled set, computes false-accept and false-reject rates with confidence intervals, and writes a report. Tuning and held-out sets are split by person.
8. **Attack set.** Print and screen-replay photos for liveness, reported as attack rejection rate.

## 11. Acceptance gates (what "10/10" means)

| Gate | Evidence required |
|---|---|
| Memory | Steady ≤ 900 MB and peak ≤ 1.2 GB on the target Linux container. |
| Latency | p95 time per request recorded and agreed with the owner. |
| Barcode | Decode rate per jurisdiction on real and synthetic samples, reported per province. |
| Face | False-accept and false-reject at the chosen threshold, with 95% intervals, including cross-age pairs. |
| Liveness | Attack rejection rate on the attack set, with its limits written down. |
| Plate | Exact-read rate on real plates, with and without the confusion rule. |
| Reliability | All failure tests pass. No `APPROVED` result is possible when any stage errors. |
| Audit | Every session verifies: signature valid, hashes match, files decrypt. |
| Retention | The sweeper deletes on schedule, proved by a test with a fake clock. |
| Docs | The README and `docs/` match the code. Unverified claims removed. |

## 12. Milestones

1. **M0, measure.** Load every model, record input and output shapes, RSS per model, and latency. Write `models.lock`. Fix the memory budget with real numbers.
2. **M1, storage.** Interface, local implementation, encryption, manifest, retention, idempotency index.
3. **M2, Stage 1.** Barcode decode, AAMVA parse, policy tables, gates. Synthetic barcode tests.
4. **M3, Stage 2.** Face, alignment, liveness, embedding. Calibration harness.
5. **M4, Stage 3.** Plate, OCR mask, colour.
6. **M5, API and page.** FastAPI wrapper, run lock, auth, the HTML page.
7. **M6, calibration and acceptance.** Run the gates in section 11 and write the report.

## 13. Assumptions and open inputs

- The owner's licensed models are the files in `backend/models/`, or replacements recorded in `models.lock`.
- A liveness model file is not in the repo. The owner supplies one or approves a candidate.
- Real sample licences for all 13 jurisdictions are needed for the class table, the restriction table and the barcode checks (M2).
- Expiry is valid through the end of the expiry date in the issuing jurisdiction's time zone.
- A request without consent fields returns `422`, not a decision.
- Age estimation is dropped. Re-adding it is a small change in Stage 2.
- The name rule stays at the owner's 85% token-sort match. A stricter exact-surname rule is recommended.
- Legal review of the policy citations remains the owner's responsibility.
