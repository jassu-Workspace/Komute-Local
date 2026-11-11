# Architecture

Komüte-Local decides `APPROVED` or `REJECTED` for a driver and vehicle with no human in the loop. It runs on CPU, one verification at a time per container, in a 1.0–1.3 GB RAM budget. It serves 13 Canadian jurisdictions.

## Request flow

```text
host app ── POST /v1/verify (multipart; X-API-Key only if the node has a key) ──► FastAPI wrapper (backend/app)
                                                         run gate: busy → 503 Retry-After
                                                         validate fields → 422 with a code
                                                         ▼
                                                      Engine (backend/core/pipeline.py)
   idempotency lookup ─► decode + cap images ─► store originals
   Stage 1 barcode + licence gates ──(any failure: stop, REJECTED)
   Stage 2 face + liveness      ┐ both run, all reasons reported together
   Stage 3 plate + colour       ┘
   decision ─► crops + compressed images ─► signed manifest ─► store response
```

## Rules the code enforces

- **Two outcomes.** `APPROVED` only if all three stages ran and no gate failed. Any doubt is `REJECTED` with reason codes, each marked retryable (a better photo could change it) or final.
- **A fault is not a decision.** A crashed stage, a failed model load, bad storage or a failed audit write returns `500 ENGINE_ERROR` and never a decision. There is exactly one catch-all, in `Engine.verify`.
- **One at a time.** A run gate returns `503` with `Retry-After` while a verification runs. This protects memory. It is not rate limiting; the host app owns that.
- **No composite score.** Hard gates only. Thresholds come from data.
- **Privacy.** Logs never contain names, dates of birth, licence numbers, plates or image bytes. Responses carry match results, not the extracted personal data. Raw barcode fields go only into the encrypted `record.json`.

## Layout

```text
backend/core/      the engine (no FastAPI imports, usable as a library)
  pipeline.py        Engine, build_engine        gates.py / policy.py   licence rules
  stages/            barcode, face, vehicle      aamva.py               barcode parser
  matching.py        names, plates, age          audit.py               session writer, manifest
  registry.py        model loading + hash lock   idempotency.py         replay index
  imaging.py         safe decode, WebP encode    liveness.py            liveness models
  hardware.py        thread and pixel clamps     config.py / contracts.py
backend/app/       thin REST layer: routes, schemas, security, run gate, error mapping
backend/static/    index.html: the one-file test page
storage/           encrypted blob store, retention sweeper (no backend imports)
scripts/           evaluate.py (calibration), bench.py (memory and latency), measure_models.py
tests/             unit, API, real-licence end-to-end (needs the owner's samples)
```

## Memory controls

Barcode variants are built one at a time. Every upload is decoded and capped to 2048 px immediately. ONNX sessions use a small arena and 2 threads. Pixel limits are enforced and the service refuses to start if the OpenCV pixel clamp is inactive. After each request the heap is trimmed where the platform allows. The compressed image tier is capped at 1280 px. Measured results are in `docs/ACCEPTANCE_REPORT.md`.
