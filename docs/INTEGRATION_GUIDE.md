# Integration guide for the main application

The verification node is a local HTTP service. The main application calls it, sends the driver's claimed details and four photos, and reads back a decision. Nothing else is needed on the main-app side.

| | |
|---|---|
| Base URL | `http://127.0.0.1:8000` (the node listens on this machine only) |
| Authentication | **None by default (testing).** If the node is started with `KOMUTE_API_KEY` set (`run.ps1 -WithApiKey`), send header `X-API-Key: <key>`; without it the node answers `401` |
| Calls | `POST /v1/verify` (the verification), `GET /v1/sessions/{request_id}` (re-read a stored result), `GET /health` (readiness) |
| Speed | typically 1.5–2 s; a photo with no barcode can take up to about 10 s before it is rejected |
| Concurrency | **one verification at a time.** A second call while one runs gets `503` |

## 1. Configuration to add

| Setting | Value | Note |
|---|---|---|
| `VERIFY_BASE_URL` | `http://127.0.0.1:8000` | Do not hard-code it |
| `VERIFY_API_KEY` | empty for now | If set, send it as `X-API-Key`; if empty, send no header |
| Connect timeout | 3 s | |
| Read timeout | **30 s** | Verifications are slow compared with normal API calls |
| `VERIFY_RETRIES_BUSY` | 3 | Wait the `Retry-After` seconds (default 5) between tries |

## 2. The request

`POST {base}/v1/verify` with `Content-Type: multipart/form-data`. Let your HTTP library set the header and the boundary. **Send the images as binary file parts, not as base64 text** (base64 adds a third more bytes and memory on both sides).

| Part | Type | Rules |
|---|---|---|
| `request_id` | text | Unique per attempt. Letters, digits, `-`, `_`, up to 64 characters. Reusing it: see section 5 |
| `driver_id` | text | Same character rules |
| `consent_at` | text | When the driver agreed to biometric processing. ISO-8601 **with a time zone**: `2026-11-11T12:00:00-05:00` or `...Z` |
| `consent_policy_version` | text | The version of the consent wording the driver saw, e.g. `v1` |
| `claimed.full_name` | text | Full legal name |
| `claimed.date_of_birth` | text | `YYYY-MM-DD` |
| `claimed.licence_number` | text | Hyphens and spaces are fine |
| `claimed.issuing_province` | text | `ON QC BC AB MB SK NB NS NL PE YT NT NU` (`NF` is accepted as `NL`) |
| `claimed.licence_class` | text | As printed, e.g. `G`, `5`. Case and spaces are ignored; must equal the barcode class (`DCA`) |
| `claimed.issue_date`, `claimed.expiry_date` | text | `YYYY-MM-DD`. Must equal the barcode issue date (`DBD`) and expiry date (`DBA`) |
| `claimed.plate_number` | text | Spaces and hyphens are fine |
| `claimed.vehicle_colour` | text | e.g. `Black`. Advisory only |
| `claimed.vehicle_make`, `claimed.vehicle_model`, `claimed.vehicle_year` | text | Optional. Stored, never checked |
| `selfie`, `licence_front`, `licence_back`, `vehicle` | file | JPEG, PNG or WebP, **at most 10 MB each**. Send the original photo: no cropping, no filters. About 1200 px or more on the long side works well. Phone orientation (EXIF) is handled |

Python (`httpx`):

```python
import httpx

with open("selfie.jpg", "rb") as s, open("front.jpg", "rb") as f, open("back.jpg", "rb") as b, open("car.jpg", "rb") as v:
    r = httpx.post(
        f"{BASE_URL}/v1/verify",
        headers={"X-API-Key": API_KEY} if API_KEY else {},
        data={
            "request_id": "req-1001", "driver_id": "drv-42",
            "consent_at": "2026-11-11T12:00:00-05:00", "consent_policy_version": "v1",
            "claimed.full_name": "Alex Tester", "claimed.date_of_birth": "1990-03-15",
            "claimed.licence_number": "T1234-56789-01234", "claimed.issuing_province": "ON",
            "claimed.plate_number": "ABC 123", "claimed.vehicle_colour": "Grey",
            "claimed.licence_class": "G", "claimed.issue_date": "2023-09-14", "claimed.expiry_date": "2030-12-31",
        },
        files={"selfie": s, "licence_front": f, "licence_back": b, "vehicle": v},
        timeout=httpx.Timeout(30.0, connect=3.0),
    )
```

Node 18+ (`fetch`, `FormData`, `Blob`):

```js
const fd = new FormData();
for (const [k, v] of Object.entries(fields)) fd.append(k, v);          // the text parts above
fd.append("selfie", new Blob([selfieBytes], { type: "image/jpeg" }), "selfie.jpg");
// ... licence_front, licence_back, vehicle the same way
const res = await fetch(`${BASE_URL}/v1/verify`, { method: "POST", headers: API_KEY ? { "X-API-Key": API_KEY } : {}, body: fd, signal: AbortSignal.timeout(30000) });
```

## 3. The response

**HTTP 200 means a decision was made.** Read `decision`.

```json
{
  "request_id": "req-1001",
  "decision": "REJECTED",
  "reasons": [
    { "code": "BARCODE_UNREADABLE", "retryable": true,
      "message": "The barcode on the back of your licence is not clearly visible. Please retake the photo of the barcode." }
  ],
  "stages": {
    "barcode": { "ran": true, "readable": false, "aamva": false, "jurisdiction": null, "gates_failed": [] },
    "face":    { "ran": false },
    "vehicle": { "ran": false }
  },
  "advisories": [],
  "timings_ms": { "total": 2210.4, "barcode": 2100.0, "face": 0.0, "vehicle": 0.0 },
  "rss_mb": 318.5,
  "audit": { "manifest_id": "aa11…", "key_id": "m1" }
}
```

| Field | Type | Meaning |
|---|---|---|
| `decision` | `"APPROVED"` \| `"REJECTED"` | The only two outcomes. There is no "review" state |
| `reasons[]` | array | Empty when approved. Every failed check is listed |
| `reasons[].code` | string | Stable code, section 4. Branch on this, not on the message |
| `reasons[].retryable` | boolean | `true`: a better photo could change the result. `false`: a new photo will not help |
| `reasons[].message` | string | A sentence safe to show to the driver |
| `stages.barcode` | object | `ran`, `readable`, `aamva`, `jurisdiction` (e.g. `"ON"`), `gates_failed` (codes), `checks` |
| `stages.barcode.checks[]` | objects | One per cross-checked field: `field`, `claimed`, `decoded`, `score` (0–100), `threshold`, `passed`. **Holds personal data.** The name is fuzzy (pass mark `KOMUTE_NAME_MATCH_THRESHOLD`, default 90); every other field is exact (100 or 0) |
| `barcode_fields` | object | Only when `KOMUTE_RESPONSE_BARCODE_FIELDS=true`: every decoded barcode element, address included. Off by default |
| `stages.face` | object | `ran`; when run: `liveness_score`, `liveness_threshold`, `similarity`, `threshold` |
| `stages.vehicle` | object | `ran`; when run: `plate_found`, `plate_read`, `plate_confidence`, `plate_matched`, `colour`, `colour_hex`, `delta_e` |
| `advisories[]` | strings | Informational only; never block approval: `COLOUR_MISMATCH`, `COLOUR_UNVERIFIED`, `LICENCE_FORMAT_UNUSUAL`, `LIVENESS_SKIPPED_DEV` |
| `timings_ms`, `rss_mb` | numbers | For monitoring |
| `audit.manifest_id`, `audit.key_id` | strings | Store the `manifest_id` with your record: it proves which signed audit record belongs to the decision |

A stage with `"ran": false` was skipped because an earlier check failed (for example, if the barcode fails, face and vehicle are not run). Fields inside a stage can be missing when it did not run, so read them defensively.

### Errors (no decision was made)

Every error has the same shape: `{"error": {"code": "...", "message": "..."}}`.

| HTTP | `error.code` | What to do |
|---|---|---|
| 422 | `MISSING_FIELD`, `INVALID_FIELD`, `CONSENT_REQUIRED`, `INVALID_IMAGE`, `IMAGE_TOO_LARGE` | A bug or bad input on your side. Fix and resend with a **new** `request_id` |
| 401 | `UNAUTHORIZED` | The node needs `X-API-Key` and it is missing or wrong |
| 409 | `REQUEST_ID_CONFLICT` | This `request_id` was used with different data. Use a new one |
| 503 | `BUSY` | One verification is running. Wait `Retry-After` seconds (header) and retry |
| 500 | `ENGINE_ERROR` | The node failed. **This is not a rejection.** Retry later and alert someone if it repeats |
| none | network error or timeout | Not a rejection either. Retry; check `GET /health` |

**Never treat a non-200 answer as `REJECTED`.** Only `200` with `decision: "REJECTED"` is a rejection.

## 4. Reason codes

| Code | Retryable | Which photo / what to tell the driver |
|---|---|---|
| `BARCODE_UNREADABLE`, `BARCODE_NOT_AAMVA` | yes | Retake the **licence back**: barcode flat, sharp, fully in frame |
| `FACE_NOT_FOUND_SELFIE`, `LIVENESS_FAILED`, `IMAGE_QUALITY` | yes | Retake the **selfie**: face the camera, good light, one person, live capture |
| `FACE_NOT_FOUND_LICENCE` | yes | Retake the **licence front**: whole card, portrait visible |
| `PLATE_NOT_FOUND`, `PLATE_UNREADABLE` | yes | Retake the **vehicle photo**: plate level, in frame, readable |
| `JURISDICTION_MISMATCH`, `NAME_MISMATCH`, `DOB_MISMATCH`, `LICENCE_NUMBER_MISMATCH`, `CLASS_MISMATCH`, `ISSUE_DATE_MISMATCH`, `EXPIRY_DATE_MISMATCH` | no | The typed details do not match the licence. Ask the driver to correct them |
| `LICENCE_EXPIRED`, `UNDERAGE`, `LICENCE_NOT_YET_VALID` | no | Not eligible (`LICENCE_NOT_YET_VALID`: the barcode issue date is after today) |
| `FACE_MISMATCH` | no | The selfie does not match the licence photo |
| `PLATE_MISMATCH` | no | The plate in the photo differs from the plate entered |

A rejection can list several reasons at once. If every reason is retryable, offer a retake; if any is not, a new photo will not change the outcome.

## 5. Retries and `request_id`

- Make a **new `request_id` for each new attempt** (for example after a retake).
- To resend the same request after a timeout, use the **same `request_id` and exactly the same data**: the node returns the stored result without running again.
- Same `request_id` with different data returns `409`.
- `GET /v1/sessions/{request_id}` returns the stored response for a finished request, or `404`.

## 6. One at a time

The node runs one verification at a time to stay inside its memory budget. For one node, queue calls on the main-app side (a single worker is enough), or retry on `503` after `Retry-After`. More throughput means more nodes behind your own router; the node does no rate limiting.

## 7. Health check

`GET /health` (no key needed) returns `200` `{"status":"ok","models_loaded":{...},"rss_mb":306.8}` when ready, `503` when a required model is not loaded. Poll it before sending traffic.

## 8. What to keep and what not to

- Store: `decision`, `request_id`, `reasons[].code`, `audit.manifest_id`. These contain no images.
- Do not store the node's response `plate_read` or the photos unless your own policy allows it: they are personal data. The node keeps its own encrypted, signed record of each session and deletes rejected-session images after 72 hours.
- Do not log request bodies.
- The `consent_at` you send is written into the node's signed record. Capture consent in your app before calling.

## 9. Checklist for the main-app team

1. Add the base URL, optional key and the timeouts in section 1 to configuration.
2. Build the multipart request (section 2) with binary image parts.
3. Treat only `200` + `decision` as a decision; map the other statuses as in section 3.
4. Use `reasons[].retryable` and the code table to drive retake prompts.
5. Generate a fresh `request_id` per attempt; reuse it only to resend identical data.
6. Serialise calls or handle `503` with `Retry-After`.
7. Add the `/health` check to your readiness probe.
8. Before going live, switch the node to authentication (`KOMUTE_API_KEY`, at least 24 characters, required when `KOMUTE_ENV=production`) and send `X-API-Key`.
