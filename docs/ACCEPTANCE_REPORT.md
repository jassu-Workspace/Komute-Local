# Acceptance report

Date: 2026-11-11. Branch `feat/verification-engine`. Machine: Windows 11, Python 3.12.13, 2 clamped threads. Full suite: **370 passed, 1 skipped** (`pytest`, about 90 s). The skipped test waits for selfie/licence pairs the owner has not supplied.

Evidence data: three real Canadian licences (front and back), synthetic AAMVA barcodes for all 13 issuers, one synthetic vehicle scene, one rendered plate. All real-data results below are counts, codes and scores. No identity value appears in this repo.

## Gates (spec section 11)

| Gate | Result | Evidence |
|---|---|---|
| **Memory** | **PASS on Windows (local). Linux deferred by the owner until handover** | 50 sequential runs: steady 334 MB, peak 383 MB, drift 0 MB (budget 900 / 1200). `docs/calibration/bench-windows.md`. The liveness model's memory is not included. The owner chose not to use Docker before handover, so the `Dockerfile` was never built or run |
| **Latency** | **MEASURED, no target agreed** | p50 1.43 s, p95 1.85 s, max 1.97 s. Stage medians: barcode 96 ms, face 485 ms, vehicle 74 ms. About 0.5 s is image encoding and encrypted writes. A photo with no barcode takes 2–6 s to reject (10 s search budget) |
| **Barcode** | **PASS on what exists; coverage is 3 of 13** | 3 of 3 real backs decoded and parsed (NS, ON, SK; 70–145 ms). 78 of 78 synthetic decodes across 13 issuers × 6 conditions (clean, blur, tilt, dark, small, rotated 90°). The real cards exposed two parser bugs (wrong subfile offset; name stored outside `DAC`), both fixed with regression tests. The other 10 provinces have never been seen on a real card |
| **Face** | **NOT MEASURED** | 3 real licence photos matched themselves at 1.0. 6 real impostor pairs scored −0.098 to 0.064 (mean −0.016). No selfie of a real person was available, so no false-reject rate exists and no cross-age pair was tested. A false-accept rate of 1 in 10,000 needs at least 29,955 impostor trials with no accepts. The 0.40 threshold is a provisional value |
| **Liveness** | **NOT MEASURED** | No liveness model exists. The code path is unit-tested with a fake model only. Single-photo liveness has known limits (see Stage 2 doc) |
| **Plate** | **PARTLY MEASURED** | The cct-xs-v2-global reader read 9 of 9 internet photos of Canadian plates exactly (lowest slot probability 0.99). These are close-ups, not onboarding photos; no real vehicle photo was tested, and plates under about 5% of the frame width were not detected in a quick test |
| **Reliability** | **PASS for the paths tested** | A stage crash, a storage failure and an input error each give an error or a 422, never a decision and never `APPROVED`. A crash mid-session followed by a retry with the same id succeeds. A second request while one runs gets `503`. A changed payload under a used id gets `409`. A model file that differs from `models.lock` stops startup. Not tested: a real killed process, a real full disk, a corrupted model file on disk beyond the hash check |
| **Audit** | **PASS** | Every session in the 45 real-card requests passed `verify_session`: signature valid, every hash matches, every file decrypts. Tampering with a file, the record, the manifest or the key is detected in unit tests |
| **Retention** | **PASS (fake clock)** | Rejected images are deleted at 72 h and kept at 71 h; approved originals at 30 d; incomplete sessions at 1 h; `record.json` and `manifest.json` always stay. A crash-left temp file is removed with its session. The in-process hourly sweeper itself is untested |
| **Docs** | **PASS** | README and `docs/` rewritten to the built system. Claims the code does not meet (650 MB, 120–160 ms, AdaFace, 36-class OCR, MiVOLO, age delta, composite score) were removed |

## Real-licence end-to-end summary

45 requests through the full stack (API, engine, real models, encrypted storage). The selfie was the licence-front photo, so this is a smoke test, **not** a biometric accuracy measure. The vehicle was synthetic. 8 approved (own-photo cases), 36 rejected, 1 replay conflict (`409`).

Rejections were the expected ones for each mutation: wrong name, licence number, province and date of birth; expired licence; one day before the 18th birthday; blank barcode photo and a photo of the card front as the back (retryable, with the retake message); blank selfie; a different real person's photo as the selfie (`FACE_MISMATCH`, final); blank vehicle photo. Stage 1 failures stopped the pipeline every time.

The NS and SK cards are rejected `CLASS_NOT_ALLOWED` in normal operation: their class `5` is not in the allowed table. The end-to-end test lets each card's own class through for that run only. The ON card (class `G`, no restrictions) passed every licence gate unchanged.

## Decisions made on the owner's behalf

See the ledger in `.superpowers/sdd/2026-11-11-komute-local-master-plan/progress.md` (git-ignored). The ones that change behaviour: name match also passes when every claimed token appears exactly in the barcode name; colour glare cutoff L\* 99 instead of 92; plate CTC decoding keeps the model's own blank decision; images are decoded before anything is stored; the compressed image tier is capped at 1280 px; the API runs through `uvicorn ... --factory`.

## Needed before production

1. A liveness model file, a threshold chosen on attack samples, and its measured memory.
2. Real selfies (5–10 people, with consent) to measure false rejects, and public cross-age and impostor sets to bound false accepts. Report intervals, not point rates.
3. A decision on NS and SK class `5`, and the allowed restriction codes for every province, from real samples.
4. A real vehicle photo set to test plate detection, reading and colour.
5. After handover to the main developers: build the image and run the memory bench on Linux (deferred by the owner; no Docker before then).
6. Real licences for the other 10 provinces, to confirm each issuer prints a readable AAMVA barcode.
7. Legal review of the Quebec Law 25 and municipal citations, the hand-controls rule, and audit-record retention.
8. Security triage of the deferred items: a minimum API key length in production, and a re-review of `storage/local.py` after its last fix.
