# Komüte-Local Verification Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline driver and vehicle verification engine, its encrypted storage, a thin REST API and a one-file test page, then prove it against the acceptance gates.

**Architecture:** A pure-Python engine package (`backend/core`) runs three stages in sequence (barcode, face, vehicle) and makes a gate-only `APPROVED`/`REJECTED` decision. A storage package (`storage/`) writes encrypted, hashed, signed session files behind a small blob interface. A FastAPI wrapper (`backend/app`) adds auth, a one-at-a-time run gate, idempotency and error mapping.

**Tech Stack:** Python 3.12, ONNX Runtime (CPU), OpenCV headless, zxing-cpp, rapidfuzz, pydantic-settings, FastAPI, uvicorn, cryptography, psutil, scipy (statistics only), pytest, httpx, Docker (Linux measurement).

**Spec:** `docs/superpowers/specs/2026-11-11-komute-local-verification-design.md`. Decisions: `CLAUDE.md`.

## Global Constraints

- Python 3.12 exactly. Install it with `uv python install 3.12`. Do not use the machine's 3.11 or 3.14.
- The venv lives at `$LOCALAPPDATA/komute/venv`, **outside OneDrive**. Storage (`KOMUTE_STORAGE_ROOT`) and real samples (`KOMUTE_SAMPLES_DIR`) also live outside OneDrive. Personal data must never sync to the cloud.
- Every shell step starts with `source scripts/dev_env.sh` (Task 0). It exports `PY`, the path to the venv's Python.
- RAM: steady-state RSS ≤ 900 MB, peak ≤ 1.2 GB, measured on Linux (Task 21).
- One verification at a time. A busy engine returns `503` with `Retry-After`. No rate limiting of any kind.
- The outcome is `APPROVED` or `REJECTED`. No review state. An engine fault returns `500`, never a decision.
- Threads: `OMP_NUM_THREADS=2`, ORT intra-op 2, inter-op 1, `cv2.setNumThreads(2)`.
- Do not add Redis, Postgres, Celery or a frontend framework. New dependencies allowed by this plan: `cryptography`, `tzdata`. Nothing else without the owner.
- Logs never contain image bytes, names, dates of birth, licence numbers or plates.
- Commits: the owner must approve git use (Task 0, Step 1) before the first commit. If not approved, skip every commit step.
- Every module boundary validates its input. No bare `except:`. Catch only specific exceptions, except the one fail-closed boundary in `Engine.verify`.

## Spec deltas (decided by this plan)

- `backend/models/models.lock` pins a SHA-256 per model file. Startup stops on a mismatch.
- Liveness is required in `KOMUTE_ENV=production`. In `dev`, `KOMUTE_DEV_SKIP_LIVENESS=true` lets the engine run without a liveness model. Every response then carries advisory `LIVENESS_SKIPPED_DEV`, and settings refuse that flag in production.
- Advisory codes: `COLOUR_MISMATCH`, `COLOUR_UNVERIFIED`, `LICENCE_FORMAT_UNUSUAL`, `LIVENESS_SKIPPED_DEV`.
- A jurisdiction with an empty class table fails closed with `CLASS_NOT_ALLOWED` until the owner's samples fill the table.
- Session commit marker: `manifest.json` is written last. A session without it is incomplete. Readers ignore it and the sweeper deletes it after 1 hour.
- Originals are stored as the uploaded bytes (encrypted), not re-encoded.
- `numpy<2.0` is dropped unless a dependency fails to install with numpy 2 (Task 0 decides and records why). `pillow` and the unused `fast-alpr`, `fast-plate-ocr`, `open-image-models`, `huggingface_hub`, `requests`, `tqdm` and `pytest-asyncio` are removed. `tzdata` is added, because Windows and slim containers lack a time-zone database.

## Review Focus

1. **Bad uploads.** Non-image bytes, truncated JPEG, a 0-byte file, a 30 MB file, a 20,000 × 20,000 PNG. Each must return `422` with a code, never `500` and never a crash. Tests: Task 3 and Task 19.
2. **Two faces.** Canadian licences often carry a small ghost portrait, and a selfie may show a second person or a held-up photo. Licence: take the largest face. Selfie: a second strong face means `IMAGE_QUALITY`. Test: Task 12.
3. **AAMVA variants.** A version 01 header without a jurisdiction version, a name only in `DAA` or `DCT` with commas, a missing `DCG`, US date order, `NF` instead of `NL`. Tests: Task 8 and Task 9.
4. **Date edges.** A 29 February date of birth, an expiry equal to today, and a run at 02:00 UTC that is still yesterday in Vancouver. Test: Task 9.
5. **Crash and retry.** A process killed mid-session leaves no visible half session. A retry with the same `request_id` and payload runs cleanly. A different payload returns `409`. Tests: Task 5, Task 6 and Task 19.

---

### Task 0: Environment and repo bootstrap

**Files:**
- Create: `scripts/dev_env.sh`, `scripts/make_dev_keys.py`, `pytest.ini`, `.gitignore`, `backend/__init__.py`, `backend/core/__init__.py`, `backend/core/stages/__init__.py`, `backend/app/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`
- Modify: `requirements.txt`, `CLAUDE.md` (Commands section)
- Delete: `storage/__pycache__/`

**Interfaces:**
- Produces: `$PY`; env vars `KOMUTE_ENV`, `KOMUTE_API_KEY`, `KOMUTE_STORAGE_ROOT`, `KOMUTE_STORAGE_KEY_B64`, `KOMUTE_STORAGE_KEY_ID`, `KOMUTE_MANIFEST_KEY_B64`, `KOMUTE_MANIFEST_KEY_ID`, `KOMUTE_SAMPLES_DIR`; pytest markers `models` and `samples`.

- [ ] **Step 1: Ask the owner whether to enable git.** If yes: `git init`, `git checkout -b feat/verification-engine`, and commit the existing files as the first commit, with the attribution line from the session.
- [ ] **Step 2: Create the venv outside OneDrive.**

```bash
uv python install 3.12
uv venv --python 3.12 "$LOCALAPPDATA/komute/venv"
```

- [ ] **Step 3: Rewrite `requirements.txt`.** Keep: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `python-dotenv`, `python-multipart`, `psutil`, `opencv-python-headless`, `numpy`, `onnxruntime`, `zxing-cpp`, `rapidfuzz`, `scipy`, `pytest`, `httpx`. Add `cryptography`, `tzdata`. Install with `uv pip install --python "$LOCALAPPDATA/komute/venv" -r requirements.txt`. If numpy 2 fails for any package, restore `numpy<2.0` and note the package in a comment. Freeze the result to `requirements.lock` with `uv pip freeze`.
- [ ] **Step 4: Write `scripts/make_dev_keys.py`.** It writes `$LOCALAPPDATA/komute/dev.env` once, with a random API key and two random 32-byte base64 keys (ids `dev-s1`, `dev-m1`), using `secrets`. It refuses to overwrite an existing file.
- [ ] **Step 5: Write `scripts/dev_env.sh`.** It exports `PY="$LOCALAPPDATA/komute/venv/Scripts/python.exe"` (or `bin/python` when that path exists), sources `dev.env`, and sets `KOMUTE_ENV=dev`, `KOMUTE_STORAGE_ROOT="$LOCALAPPDATA/komute/storage"` and `KOMUTE_SAMPLES_DIR="$LOCALAPPDATA/komute/samples"`.
- [ ] **Step 6: Write `pytest.ini`** with `pythonpath = .`, `testpaths = tests`, and two markers: `models` (needs ONNX files) and `samples` (needs `KOMUTE_SAMPLES_DIR`). `tests/conftest.py` skips `samples` tests when that directory is missing or empty.
- [ ] **Step 7: Write `.gitignore`.** Include `__pycache__/`, `*.pyc`, `.venv/`, `*.env`, `storage/uploads/`, `samples/`, `.pytest_cache/`.
- [ ] **Step 8: Write the smoke test** `tests/test_smoke.py::test_imports`. It imports `cv2`, `onnxruntime`, `zxingcpp`, `rapidfuzz`, `cryptography` and `zoneinfo.ZoneInfo("America/Toronto")`.
- [ ] **Step 9: Run it.** `source scripts/dev_env.sh && "$PY" -m pytest tests/test_smoke.py -v`. Expected: 1 passed.
- [ ] **Step 10: Update the CLAUDE.md "Commands" section** with the real commands from Steps 2–9.
- [ ] **Step 11: Commit** `chore: bootstrap env, deps and test harness`.

### Task 1: Model facts, lock file and registry

**Files:**
- Create: `scripts/measure_models.py`, `docs/MODEL_FACTS.md`, `backend/models/models.lock`, `backend/core/registry.py`, `tests/core/test_registry.py`

**Interfaces:**
- Consumes: `ort_session_options()` from Task 2. If Task 2 is not done yet, build options inline and switch them after Task 2.
- Produces:
  - `verify_lock(models_dir: Path, lock_path: Path) -> None`, which raises `ModelHashMismatch(name: str)`.
  - `class ModelRegistry` with `__init__(models_dir: Path, lock_path: Path, liveness_path: Path | None)`, `load() -> None`, `session(name: Literal["face_embedder","plate_detector","plate_ocr","liveness"]) -> ort.InferenceSession`, `face_detector_path: Path`, `plate_charset: list[str]`, and `loaded: dict[str, bool]`.

- [ ] **Step 1: Write `scripts/measure_models.py`.** For each `.onnx` in `backend/models/`, it prints the SHA-256, the input and output names, shapes and dtypes, the RSS before and after load (psutil), and the latency of 5 runs on zero input of the declared shape. Dynamic dimensions are set to: OCR width 320, YOLO 384. It also prints `len(plate_ocr_dict.json)` and the OCR output class count. It writes the lock JSON `{filename: sha256}` and appends a table to `docs/MODEL_FACTS.md`.
- [ ] **Step 2: Run it.** `"$PY" scripts/measure_models.py`. Expected: one row per model and no exception. Record in `docs/MODEL_FACTS.md`:
  - The YOLO end-to-end output layout, meaning which column is which. Read it from the output shape and from a run on a sample vehicle image if one exists.
  - The OCR class-count rule: the number of classes is `len(dict) + 2` (blank first, space last) or `len(dict) + 1`.
  - Save the raw YOLO output for one image with a visible plate to `tests/fixtures/yolo_output.npy`, with its expected box in `tests/fixtures/yolo_output.json` (`{"scale", "pad", "box"}`). Task 14 tests against it. If no vehicle sample exists yet, Task 14 creates the fixture when the first sample arrives.
- [ ] **Step 3: Write failing tests.**
  - `test_verify_lock_passes_on_true_hashes`
  - `test_verify_lock_raises_on_tampered_file`: copy a small model to `tmp_path`, flip one byte, expect `ModelHashMismatch`.
  - `test_registry_loads_all_sessions` (marker `models`): every name loads and `loaded` is all true, with liveness absent when `liveness_path=None`.
- [ ] **Step 4: Run them.** `"$PY" -m pytest tests/core/test_registry.py -v`. Expected: FAIL (module missing).
- [ ] **Step 5: Implement `backend/core/registry.py`.** It loads lazily once in `load()`. `plate_charset` is built from `plate_ocr_dict.json` following the class-count rule recorded in Step 2.
- [ ] **Step 6: Run the tests.** Expected: PASS.
- [ ] **Step 7: Commit** `feat: model facts, lock file and verified registry`.

### Task 2: Contracts, config and hardware clamps

**Files:**
- Create: `backend/core/contracts.py`, `backend/core/config.py`, `backend/core/hardware.py`, `tests/core/test_contracts.py`, `tests/core/test_config.py`
- Modify: `backend/core/__init__.py`. Its first lines call `hardware.apply_env_clamps()` before anything imports `cv2`.

**Interfaces:**
- Produces in `contracts.py`:
  - `class ReasonCode(StrEnum)` with exactly the 19 codes from spec section 2.5.
  - `RETRYABLE: frozenset[ReasonCode]`, the "yes" rows of 2.5.
  - `MESSAGES: dict[ReasonCode, str]`, one plain sentence each. `BARCODE_UNREADABLE` is "The barcode on the back of your licence is not clearly visible. Please retake the photo of the barcode."
  - `@dataclass(frozen=True) class Reason(code: ReasonCode, retryable: bool, message: str)` with `@classmethod of(code) -> Reason`.
  - `class Advisory(StrEnum)` with the four advisory codes.
  - `@dataclass(frozen=True) class Claimed(full_name: str, date_of_birth: date, licence_number: str, issuing_province: str, plate_number: str, vehicle_colour: str, vehicle_make: str | None, vehicle_model: str | None, vehicle_year: int | None)`.
  - `@dataclass class StageResult(name: Literal["barcode","face","vehicle"], ran: bool, reasons: list[Reason], advisories: list[Advisory], details: dict[str, Any], timings_ms: dict[str, float], crops: dict[str, np.ndarray])`.
  - `class InputError(Exception)` and `class EngineError(Exception)`, both with `code: str`.
- Produces in `config.py`: `class Settings(BaseSettings)` with prefix `KOMUTE_`. Fields: `env: Literal["dev","production"]="dev"`, `api_key: SecretStr`, `storage_root: Path`, `storage_key_b64: SecretStr`, `storage_key_id: str`, `manifest_key_b64: SecretStr`, `manifest_key_id: str`, `models_dir: Path = Path("backend/models")`, `liveness_model: Path | None = None`, `dev_skip_liveness: bool = False`, `face_match_threshold: float = 0.40`, `liveness_threshold: float = 0.5`, `plate_min_confidence: float = 0.6`, `max_upload_bytes: int = 10_000_000`, `max_image_side: int = 2048`, `retry_after_s: int = 5`, `rejected_images_ttl_h: int = 72`, `approved_originals_ttl_d: int = 30`, `sweep_interval_s: int = 3600`. Also `get_settings() -> Settings` (cached).
- Produces in `hardware.py`:
  - `apply_env_clamps() -> None`. It sets the thread variables and `OPENCV_IO_MAX_IMAGE_PIXELS=40000000` with `os.environ.setdefault`.
  - `ort_session_options() -> ort.SessionOptions`, with intra 2, inter 1, `enable_cpu_mem_arena=False` and `enable_mem_pattern=False` (Task 21 may flip them using measurements).
  - `rss_mb() -> float`.
  - `trim_heap() -> None`, which calls `malloc_trim(0)` through ctypes on Linux and does nothing elsewhere.

- [ ] **Step 1: Write failing tests.**
  - `test_every_code_has_message_and_retry_flag_matches_spec`: the retryable set equals `{BARCODE_UNREADABLE, BARCODE_NOT_AAMVA, FACE_NOT_FOUND_SELFIE, FACE_NOT_FOUND_LICENCE, IMAGE_QUALITY, PLATE_NOT_FOUND, PLATE_UNREADABLE, LIVENESS_FAILED}`.
  - `test_keys_must_decode_to_32_bytes`: a 16-byte key raises `ValidationError`.
  - `test_production_rejects_dev_skip_liveness`
  - `test_production_requires_liveness_model`
  - `test_storage_root_inside_onedrive_rejected`: any path containing the `OneDrive` segment raises `ValidationError` (guards against syncing personal data).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the three modules.** Key validation uses `base64.b64decode(..., validate=True)` and a length check.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: contracts, settings and hardware clamps`.

### Task 3: Image ingest

**Files:**
- Create: `backend/core/imaging.py`, `tests/core/test_imaging.py`

**Interfaces:**
- Produces:
  - `decode_image(data: bytes, max_side: int) -> np.ndarray`, which returns BGR uint8 with EXIF orientation applied by `cv2.imdecode(..., IMREAD_COLOR)`, downscaled with `INTER_AREA` so the long side is at most `max_side`. It raises `InputError("INVALID_IMAGE")`.
  - `encode_webp(img: np.ndarray, quality: int) -> bytes`
  - `IMAGE_KEYS = ("selfie", "licence_front", "licence_back", "vehicle")`

- [ ] **Step 1: Write failing tests (Review Focus 1).**
  - `test_rejects_empty_bytes`
  - `test_rejects_random_bytes`
  - `test_rejects_truncated_jpeg`: encode a JPEG and cut it to half. Expect `INVALID_IMAGE`, or a decoded image whose shape is still valid. Assert the outcome is one of these two, never an exception other than `InputError`.
  - `test_rejects_pixel_bomb`: a 20000 × 20000 PNG made with `cv2.imencode` from a 1-channel array.
  - `test_downscales_long_side_to_max`
  - `test_keeps_small_image_size`
  - `test_applies_exif_orientation`: a JPEG with an EXIF orientation of 6, built with a minimal APP1 segment, decodes rotated.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `cv2.imdecode` returns `None` on failure, which raises `InputError`. Catch `cv2.error` and raise `InputError`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: safe image decode and size cap`.

### Task 4: Encrypted blob storage

**Files:**
- Create: `storage/paths.py` (moved `sanitize_folder_name`), `storage/base.py`, `storage/crypto.py`, `storage/local.py`, `tests/storage/test_crypto.py`, `tests/storage/test_local.py`
- Modify: `storage/__init__.py`. It exports `sanitize_folder_name`, `BlobStore`, `Cipher`, `LocalStore` only, with no import side effects.
- Delete: `storage/storage_manager.py`. Its only reusable piece is `sanitize_folder_name`, moved unchanged. Nothing else imports it.

**Interfaces:**
- Produces:
  - `class BlobStore(Protocol)` with `put(key: str, data: bytes) -> None`, `get(key: str) -> bytes`, `exists(key: str) -> bool`, `delete_prefix(prefix: str) -> int`, `list_prefix(prefix: str) -> list[str]`.
  - `class Cipher` with `__init__(key: bytes, key_id: str)`, `encrypt(plaintext: bytes, aad: bytes) -> bytes`, `decrypt(blob: bytes, aad: bytes) -> bytes`. The format is `b"KMT1" + len(key_id) (1 byte) + key_id + nonce(12) + AESGCM ciphertext`. Decryption with an unknown key id or a bad tag raises `StorageIntegrityError`.
  - `class LocalStore(BlobStore)` with `__init__(root: Path, cipher: Cipher)`. A key is a `/`-separated path. Every segment must equal `sanitize_folder_name(segment)`, otherwise `ValueError`. Writes go to `<file>.tmp`, then `fsync`, then `os.replace`. The AAD is the key bytes.

- [ ] **Step 1: Write failing tests.**
  - `test_roundtrip`
  - `test_tamper_detected`: flip one byte in the file on disk, then expect `StorageIntegrityError` from `get`.
  - `test_file_swap_detected`: copy file A's bytes over file B, then expect an error, because the AAD differs.
  - `test_rejects_traversal_keys`, with `../x`, `a/../../b`, `C:\\x`, `a//b`.
  - `test_plaintext_never_on_disk`: put `b"SECRET-NAME"`, then scan the root's bytes for that string. Expect none.
  - `test_delete_prefix_counts`
  - `test_tmp_file_left_by_crash_is_ignored_by_list`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with `os.urandom(12)` nonces.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: encrypted atomic blob storage`.

### Task 5: Session writer and signed manifest

**Files:**
- Create: `backend/core/audit.py`, `tests/core/test_audit.py`

**Interfaces:**
- Consumes: `BlobStore` (Task 4).
- Produces:
  - `session_prefix(driver_id: str, request_id: str) -> str`, which returns `sessions/{driver}/{request}`.
  - `class SessionWriter` with `__init__(store: BlobStore, prefix: str, manifest_key: bytes, manifest_key_id: str, now: datetime)`, `put(rel_path: str, data: bytes) -> None` (records the SHA-256 of the plaintext), and `commit(record: dict) -> str`. The constructor writes `started.json` (`{"created_at": now.isoformat()}`) before anything else, so the sweeper can age incomplete sessions. `commit` writes `record.json`, then writes `manifest.json` last as `{"files": {rel: sha}, "record_sha256", "key_id", "created_at", "signature"}`, and returns the manifest id (the SHA-256 of the canonical manifest).
  - `canonical_json(obj) -> bytes` with `sort_keys=True`, `separators=(",", ":")` and `ensure_ascii=False`.
  - `verify_session(store, prefix, manifest_key) -> VerifyReport(signature_ok: bool, mismatched: list[str], missing: list[str])`.
  - `is_committed(store, prefix) -> bool`.

- [ ] **Step 1: Write failing tests (Review Focus 5).**
  - `test_commit_then_verify_ok`
  - `test_modified_record_fails_signature`
  - `test_modified_file_reported_mismatched`
  - `test_deleted_file_reported_missing_not_mismatched`
  - `test_uncommitted_session_not_committed`: call `put` without `commit`, then expect `is_committed` to be false.
  - `test_signature_uses_hmac_sha256`: recompute it independently with `hmac.new` in the test.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Compare signatures with `hmac.compare_digest`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: session writer with signed manifest`.

### Task 6: Retention sweeper and idempotency index

**Files:**
- Create: `storage/retention.py`, `backend/core/idempotency.py`, `tests/storage/test_retention.py`, `tests/core/test_idempotency.py`

**Interfaces:**
- Consumes: `BlobStore`, `is_committed`, `session_prefix`.
- Produces:
  - `@dataclass class RetentionPolicy(rejected_images: timedelta, approved_originals: timedelta, incomplete: timedelta = timedelta(hours=1))`
  - `sweep(store: BlobStore, now: datetime, policy: RetentionPolicy) -> SweepReport(deleted_keys: int, sessions_seen: int)`. It reads `record.json` for `decision` and `created_at`. For `REJECTED` past TTL it deletes `originals/`, `cropped/` and `compressed/`. For `APPROVED` past TTL it deletes `originals/`. For a session that is not committed and whose `started.json` `created_at` is older than `incomplete`, it deletes the whole prefix. It keeps `record.json` and `manifest.json`.
  - `class IdempotencyConflict(Exception)`
  - `lookup(store, request_id: str, payload_sha256: str) -> dict | None`, which raises `IdempotencyConflict` when the stored hash differs.
  - `save(store, request_id: str, driver_id: str, payload_sha256: str, response: dict) -> None`, with the key `requests/{request_id}.json`.

- [ ] **Step 1: Write failing tests with an injected `now`.**
  - `test_rejected_images_deleted_after_72h_record_kept`
  - `test_rejected_images_kept_at_71h`
  - `test_approved_originals_deleted_after_30d_crops_and_compressed_kept`
  - `test_incomplete_session_deleted_after_1h`
  - `test_lookup_returns_stored_response`
  - `test_lookup_different_payload_raises_conflict`
  - `test_lookup_unknown_returns_none`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: retention sweeper and idempotency index`.

### Task 7: Matching helpers

**Files:**
- Create: `backend/core/matching.py`, `tests/core/test_matching.py`

**Interfaces:**
- Produces:
  - `normalise_name(s: str) -> str`: NFKD normalisation, drop combining marks, uppercase, every non-alphanumeric character to a space, collapse spaces.
  - `names_match(claimed: str, document: str, threshold: float = 85.0) -> tuple[bool, float]`, using `rapidfuzz.fuzz.token_sort_ratio` on the normalised strings.
  - `normalise_licence(s: str) -> str`: uppercase, keep only `A–Z`, `0–9` and `*`.
  - `normalise_plate(s: str) -> str`: uppercase `A–Z` and `0–9` only.
  - `CONFUSION_PAIRS = {frozenset("O0"), frozenset("I1"), frozenset("B8")}`
  - `plates_match(read: str, claimed: str) -> bool`: normalise both. True if equal, or if the lengths are equal and exactly one position differs and that pair is in `CONFUSION_PAIRS`.
  - `age_on(dob: date, on: date) -> int`, so a 29 February birthday turns a year older on 1 March in non-leap years.

- [ ] **Step 1: Write failing tests.**
  - `names_match("Zoë Tremblay-Côté", "TREMBLAY COTE, ZOE")` is true.
  - `names_match("John Smith", "SMITH, JOHN ANDREW")` is true when the score is ≥ 85. Assert the actual score, documenting the 85% behaviour.
  - `names_match("John Smith", "SMYTH, JON")` documents that it passes or fails by assertion on the score, to pin the known weakness.
  - `names_match("Ana Lee", "BOB KHAN")` is false.
  - Plates: `plates_match("ABC1O3", "ABC103")` true. `plates_match("ABC123", "ABK123")` false. `plates_match("ABC 123", "abc-123")` true. `plates_match("AB0O23", "ABOO23")` true (one differing position). `plates_match("8B0123", "BBO123")` false (two differing positions). `plates_match("", "ABC123")` false.
  - `age_on(date(2008,2,29), date(2026,2,28)) == 17` and `age_on(date(2008,2,29), date(2026,3,1)) == 18` (Review Focus 4).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: name, plate, licence and age helpers`.

### Task 8: AAMVA parser

**Files:**
- Create: `backend/core/aamva.py`, `tests/core/test_aamva.py`, `tests/fixtures/aamva_factory.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AamvaRecord(iin: str, version: str, fields: dict[str, str])` with `country() -> str | None` (`DCG`), `date(element: str) -> date | None`, and `full_name() -> str`. `full_name` uses `DAC DAD DCS` when present, else `DCT` plus `DCS`, else `DAA`. Commas become spaces.
  - `parse_aamva(text: str) -> AamvaRecord | None`. It returns `None` when the text is not AAMVA.
  - `date_order(country: str | None, value: str) -> Literal["CCYYMMDD","MMDDCCYY"] | None`, using the rules and heuristic from `docs/STAGE1_BARCODE_SPECIFICATION.md` section 3.1.
  - In the fixture: `make_aamva_text(iin: str, version: str = "09", fields: dict[str, str], extra_subfiles: dict[str, dict[str, str]] | None = None) -> str`. It builds a correct header and subfile directory with true offsets.

Header rules to implement:
- The text starts with `@`, then LF, RS, CR, then `ANSI ` or `AAMVA`.
- Then IIN (6), version (2), and a jurisdiction version (2) **only when version ≥ 02**, then the entry count (2).
- Each entry is type (2), offset (4) and length (4).
- An element is 3 uppercase letters followed by its value up to LF or CR.
- Strip the subfile type prefix (`DL`, `ZO`) from the subfile body.
- Use a linear-scan fallback when the directory yields no fields.

- [ ] **Step 1: Write failing tests (Review Focus 3).**
  - `test_ontario_sample_from_docs`: built with the factory from the flat fields in `docs/STAGE1_BARCODE_SPECIFICATION.md` section 7, plus the `ZO` subfile. Assert `fields["DAQ"] == "G62090000000429"`, `date("DBB") == date(2000,4,29)`, `iin == "636012"`.
  - `test_us_date_order`: `DCG=USA` and `DBB=04292000` give 2000-04-29.
  - `test_missing_dcg_uses_heuristic`
  - `test_version_01_header_without_jurisdiction_version`
  - `test_name_from_daa_with_commas`: `DAA="SMITH,JOHN,A"` gives `full_name()` containing `SMITH`, `JOHN` and `A`.
  - `test_name_from_dct`
  - `test_corrupt_directory_falls_back_to_linear_scan`
  - `test_non_aamva_returns_none`
  - `test_invalid_date_returns_none`: month 13.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: AAMVA header, directory and element parser`.

### Task 9: Policy tables and licence gates

**Files:**
- Create: `backend/core/policy.py`, `backend/core/gates.py`, `tests/core/test_policy.py`, `tests/core/test_gates.py`

**Interfaces:**
- Consumes: `AamvaRecord`, `Claimed`, `Reason`, `ReasonCode`, `Advisory`, matching helpers.
- Produces in `policy.py`:
  - `PROVINCES` (13 codes).
  - `IIN_TO_PROVINCE`, copied from the CLAUDE.md table.
  - `normalise_province(code: str) -> str`, which maps `NF` to `NL` and raises `ValueError` for anything else outside the 13.
  - `LICENCE_PATTERNS: dict[str, re.Pattern]`, the owner's 13 regexes from CLAUDE.md, compiled.
  - `TIMEZONES` = ON `America/Toronto`, QC `America/Toronto`, BC `America/Vancouver`, AB `America/Edmonton`, MB `America/Winnipeg`, SK `America/Regina`, NB `America/Moncton`, NS `America/Halifax`, NL `America/St_Johns`, PE `America/Halifax`, YT `America/Whitehorse`, NT `America/Edmonton`, NU `America/Iqaluit`.
  - `ALLOWED_CLASSES` = ON `{"G"}`, QC, BC and AB `{"5"}`, others empty.
  - `ALLOWED_RESTRICTIONS`, empty for all 13 until samples arrive.
  - `NO_RESTRICTION_VALUES = {"", "NONE"}`
  - `MIN_AGE = 18`
- Produces in `gates.py`: `licence_gates(record: AamvaRecord, claimed: Claimed, now_utc: datetime) -> tuple[list[Reason], list[Advisory]]`. The order is: jurisdiction, licence number, name, date of birth, expiry, age, class, restriction. All failures are collected.
  - **Jurisdiction:** `IIN_TO_PROVINCE.get(iin)`, `normalise_province(DAJ)` and the claimed province must all be equal, otherwise `JURISDICTION_MISMATCH`.
  - **Licence number:** `normalise_licence(DAQ) == normalise_licence(claimed)`, otherwise `LICENCE_NUMBER_MISMATCH`. If `DAQ` with hyphens removed fails the province regex, add advisory `LICENCE_FORMAT_UNUSUAL`.
  - **Expiry and age:** the "today" date is `now_utc.astimezone(ZoneInfo(TIMEZONES[province])).date()`. The licence is valid when `today <= DBA`. A missing `DBA` or `DBB` is a failure (`LICENCE_EXPIRED` or `DOB_MISMATCH`).
  - **Class:** `DCA` stripped and uppercased must be in `ALLOWED_CLASSES[province]`, otherwise `CLASS_NOT_ALLOWED`.
  - **Restrictions:** split `DCB` on spaces and commas. Each code not in `NO_RESTRICTION_VALUES` must be in `ALLOWED_RESTRICTIONS[province]`, otherwise `RESTRICTION_UNKNOWN`. `RESTRICTION_NOT_ALLOWED` is reserved for codes listed as blocked once the tables exist.

- [ ] **Step 1: Write failing tests.**
  - `test_iin_table_has_13_entries_and_matches_claude_md`
  - `test_nf_normalises_to_nl`
  - `test_all_pass_for_valid_ontario_g`
  - `test_g2_rejected_class`
  - `test_expiry_today_passes` and `test_expiry_yesterday_fails`
  - `test_vancouver_midnight_boundary`: `now_utc = 2026-06-02T02:00Z` and `DBA = 2026-06-01` with province BC passes, because it is still 1 June locally (Review Focus 4).
  - `test_underage_17`
  - `test_unknown_restriction_fails_closed`
  - `test_quebec_empty_table_class_ok_when_5`
  - `test_manitoba_empty_class_table_fails_closed`
  - `test_dob_mismatch_by_one_day`
  - `test_collects_multiple_failures`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: jurisdiction policy and licence gates`.

### Task 10: PDF417 decode with lazy variants

**Files:**
- Create: `backend/core/stages/barcode.py` (decode part), `tests/core/test_barcode_decode.py`
- Modify: `tests/fixtures/aamva_factory.py`, adding `render_pdf417(text: str, module_px: int = 3) -> np.ndarray` and `distort(img, kind: Literal["blur","rotate90","perspective","dark","small"]) -> np.ndarray`

**Interfaces:**
- Produces:
  - `iter_variants(gray: np.ndarray) -> Iterator[np.ndarray]`. It yields one grayscale uint8 array at a time, in the order of the spec's Stage 1 list (original, 1.6×, 2.5×, sharpened, Otsu, 1.8× Otsu, inverted, ±90°, four quadrant crops, top and bottom halves, 2× crops of the two halves). A variant is skipped when it would exceed 25 megapixels.
  - `decode_pdf417(img_bgr: np.ndarray) -> str | None`. It converts to grayscale once and, for each variant, calls `zxingcpp.read_barcodes(v, formats=zxingcpp.BarcodeFormat.PDF417, try_rotate=True, try_downscale=True, binarizer=b)` for `b` in `(LocalAverage, GlobalHistogram)`. It returns the first result's `bytes.decode("latin-1")`. Each variant is deleted before the next one is built.
- Factory rendering uses `zxingcpp.create_barcode(...).to_image()` when available, else `zxingcpp.write_barcode(zxingcpp.BarcodeFormat.PDF417, text, ...)`. The test records which API exists.

- [ ] **Step 1: Write failing tests.**
  - A parametrised `test_decodes_synthetic_card` across all 13 IINs and the 5 distortions. Each card is the barcode pasted on a 1600 × 1000 grey canvas with random noise. Assert that `parse_aamva(decode_pdf417(img)).iin` equals the IIN.
  - `test_returns_none_for_blank_card`
  - `test_ignores_code128`: a card with only a Code 128 barcode returns `None`.
  - `test_peak_memory_bounded`: `tracemalloc` peak for one 2048 × 1536 decode is under 150 MB, which proves variants are lazy.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Record any distortion that fails in `docs/MODEL_FACTS.md` and fix it by adding or reordering a variant, not by weakening the test.
- [ ] **Step 5: Commit** `feat: lazy multi-variant PDF417 decoding`.

### Task 11: Stage 1 assembly

**Files:**
- Modify: `backend/core/stages/barcode.py`
- Create: `tests/core/test_stage_barcode.py`

**Interfaces:**
- Consumes: `decode_pdf417`, `parse_aamva`, `licence_gates`.
- Produces: `run_barcode_stage(licence_back: np.ndarray, claimed: Claimed, now_utc: datetime) -> tuple[StageResult, AamvaRecord | None]`. Its `details` holds `{"readable": bool, "aamva": bool, "jurisdiction": str | None, "gates_failed": [codes]}` and contains no personal fields.

- [ ] **Step 1: Write failing tests.**
  - `test_unreadable_gives_retryable_barcode_unreadable`, whose message equals `MESSAGES[BARCODE_UNREADABLE]`.
  - `test_pdf417_not_aamva_gives_barcode_not_aamva`
  - `test_valid_card_passes`
  - `test_details_have_no_pii`: serialise the details and assert that no claimed name, licence number or date of birth substring appears.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Record `timings_ms` as `{"decode": ..., "parse": ..., "gates": ...}`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: stage 1 barcode stage`.

### Task 12: Face detection and alignment

**Files:**
- Create: `backend/core/stages/face.py` (detection and alignment), `tests/core/test_face_detect.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class FaceBox(score: float, box: tuple[int,int,int,int], landmarks: np.ndarray)`, with landmarks of shape (5, 2) in original-image pixels.
  - `class FaceDetector` with `__init__(model_path: Path)` and `detect(img_bgr: np.ndarray) -> list[FaceBox]`. It runs `cv2.FaceDetectorYN.create(path, "", (w,h), score_threshold=0.7, nms_threshold=0.3, top_k=50)` on a copy scaled so the long side is ≤ 640, then maps coordinates back.
  - `REFERENCE_112`: the 5-point InsightFace coordinates from `docs/STAGE2_BIOMETRICS_SPECIFICATION.md` section 2.2.
  - `align_112(img_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray`, using `cv2.estimateAffinePartial2D(landmarks, REFERENCE_112, method=cv2.LMEDS)` and `warpAffine` to (112, 112). It raises `EngineError("ALIGN_FAILED")` when the matrix is `None`.
  - `pick_licence_face(faces: list[FaceBox]) -> FaceBox | None`: the largest box area.
  - `pick_selfie_face(faces: list[FaceBox]) -> FaceBox | Reason`. It returns `Reason.of(FACE_NOT_FOUND_SELFIE)` for none, and `Reason.of(IMAGE_QUALITY)` when a second face has a score ≥ 0.9 and an area ≥ 25% of the largest.

- [ ] **Step 1: Write failing tests (Review Focus 2).**
  - `test_align_maps_reference_points_to_themselves`: landmarks equal to `REFERENCE_112` scaled ×3 in a 336 × 336 image align to within 1 px.
  - `test_pick_licence_face_takes_largest_ignores_ghost`, using synthetic `FaceBox` lists.
  - `test_selfie_second_strong_face_is_image_quality`
  - `test_selfie_small_background_face_ignored`
  - `test_detector_runs_on_blank_image_returns_empty` (marker `models`)
  - `test_detector_finds_sample_faces` (marker `samples`)
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: face detection, selection and alignment`.

### Task 13: Embedding, liveness and Stage 2 assembly

**Files:**
- Modify: `backend/core/stages/face.py`
- Create: `backend/core/liveness.py`, `tests/core/test_stage_face.py`

**Interfaces:**
- Consumes: `FaceDetector`, `align_112`, the pickers, `ModelRegistry.session("face_embedder")`.
- Produces:
  - `embed(aligned: np.ndarray, session: ort.InferenceSession) -> np.ndarray`. It converts BGR to RGB, applies `(x - 127.5) / 127.5`, makes NCHW float32, runs the session, and returns a (512,) L2-normalised array.
  - `cosine(a: np.ndarray, b: np.ndarray) -> float`.
  - In `liveness.py`: `class LivenessModel(Protocol)` with `score(img_bgr: np.ndarray, face: FaceBox) -> float` (probability live, 0–1). Also `class OnnxLiveness(LivenessModel)` with `__init__(session, crop_scale: float, input_size: int, live_index: int)`. The constructor values come from the owner-supplied model's facts, recorded in `docs/MODEL_FACTS.md` when the file arrives. Also `class DevSkipLiveness`, which returns 1.0 and exists only for `dev_skip_liveness`.
  - `run_face_stage(selfie, licence_front, detector, embedder_session, liveness, settings) -> StageResult`, with crops `{"selfie_face", "licence_face"}` (112 × 112) and details `{"similarity", "threshold", "liveness_score", "liveness_threshold"}`.
  - The order is: selfie face pick, liveness (`LIVENESS_FAILED` if below threshold), licence face pick (`FACE_NOT_FOUND_LICENCE`), embeddings, then `FACE_MISMATCH` if the similarity is below the threshold.

- [ ] **Step 1: Write failing tests.**
  - `test_embed_shape_and_unit_norm` (marker `models`): random 112 × 112 input gives shape (512,) and a norm within 1e-4 of 1.0.
  - `test_cosine_identical_is_one`
  - `test_stage_liveness_fail_short_circuits_match`: with a fake detector and a fake liveness model returning 0.1, the reasons are exactly `[LIVENESS_FAILED]`.
  - `test_stage_mismatch`: with fakes, the embedder is replaced by a function returning orthogonal vectors.
  - `test_stage_match`
  - `test_same_person_samples_match` (marker `samples`): pairs listed in `$KOMUTE_SAMPLES_DIR/pairs.csv` with `same_person=1` exceed the threshold. This is informational until Task 17 calibration.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Inject the detector, the embedder callable and the liveness model so tests use fakes.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: stage 2 liveness, embedding and match`.

### Task 14: Plate detection and masked OCR

**Files:**
- Create: `backend/core/stages/vehicle.py` (plate part), `tests/core/test_plate.py`

**Interfaces:**
- Consumes: `ModelRegistry.session("plate_detector")`, `session("plate_ocr")`, `plate_charset`, and the facts in `docs/MODEL_FACTS.md`.
- Produces:
  - `@dataclass(frozen=True) class PlateBox(x1: int, y1: int, x2: int, y2: int, score: float)`
  - `letterbox(img, size: int = 384) -> tuple[np.ndarray, float, tuple[int,int]]`, returning the tensor, scale and padding.
  - `decode_end2end(output: np.ndarray, scale: float, pad: tuple[int,int], min_score: float = 0.35) -> list[PlateBox]`, using the column layout recorded in Task 1.
  - `detect_plate(img_bgr, session) -> PlateBox | None`: the highest score.
  - `allowed_indices(charset: list[str]) -> np.ndarray`: index 0 (blank) plus the indices of `A–Z` and `0–9`.
  - `read_plate(crop_bgr, session, charset, allowed) -> tuple[str, float]`. It resizes to height 48 with the aspect kept and the width capped at 320, pads right, applies `(x / 255 - 0.5) / 0.5`, and makes NCHW. Greedy CTC runs over `allowed` columns only, collapsing repeats and dropping blanks. Confidence is the mean of the chosen character probabilities, or 0.0 when empty.

- [ ] **Step 1: Write failing tests.**
  - `test_letterbox_roundtrip_coordinates`
  - `test_decode_end2end_on_recorded_fixture`, using the array saved in `tests/fixtures/yolo_output.npy` during Task 1 and the expected box.
  - `test_ctc_masked_decode_ignores_chinese_columns`: a synthetic probability matrix whose highest column is a Chinese character still yields the best allowed letter.
  - `test_ctc_collapses_repeats_and_blanks`
  - `test_reads_rendered_plate` (marker `models`): `cv2.putText` draws `ABC123` in black on white at 300 × 100, and `read_plate` returns `ABC123`.
  - `test_detects_sample_plates` (marker `samples`)
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. If `test_reads_rendered_plate` fails, record it in `docs/MODEL_FACTS.md` and raise it with the owner, because the spec names `fast-plate-ocr` as the fallback.
- [ ] **Step 5: Commit** `feat: plate detection and masked CTC OCR`.

### Task 15: Colour and Stage 3 assembly

**Files:**
- Modify: `backend/core/stages/vehicle.py`
- Create: `tests/core/test_stage_vehicle.py`

**Interfaces:**
- Produces:
  - `PALETTE`: the 14 entries from `docs/STAGE3_ALPR_SPECIFICATION.md` section 4.4.
  - `COLOUR_FAMILIES: dict[str, set[str]]`, mapping claimed words to palette names. For example `"grey"`, `"gray"`, `"charcoal"` and `"graphite"` map to `{"Grey","Dark Charcoal / Graphite"}`, and `"silver"` maps to `{"Silver / Metallic"}`.
  - `@dataclass(frozen=True) class ColourResult(name: str, hex: str, delta_e: float)`
  - `classify_colour(img_bgr, plate: PlateBox) -> ColourResult | None`. It takes the four patches from spec section 4.2, clipped to the image, converts with `cv2.cvtColor(float32 / 255, COLOR_BGR2Lab)`, keeps pixels with 8 < L < 92, runs `cv2.kmeans` with K=3, takes the largest cluster, and finds the nearest palette entry by CIE76. It returns `None` when fewer than 200 pixels remain.
  - `run_vehicle_stage(vehicle_img, claimed, detector_session, ocr_session, charset, allowed, settings) -> StageResult`, with reasons `PLATE_NOT_FOUND`, `PLATE_UNREADABLE` (empty, or confidence below `plate_min_confidence`) and `PLATE_MISMATCH`, and advisories `COLOUR_MISMATCH` or `COLOUR_UNVERIFIED` (unknown claimed word or `None` result). Details: `{"plate_read", "plate_matched", "colour", "colour_hex", "delta_e"}`. Crop: `{"plate"}`.

- [ ] **Step 1: Write failing tests.**
  - `test_solid_red_patch_is_red`: a synthetic image with a red body and a white plate box.
  - `test_glare_pixels_filtered`
  - `test_colour_mismatch_is_advisory_not_reason`
  - `test_unknown_claimed_colour_unverified`
  - `test_plate_missing_gives_retryable`
  - `test_plate_confusion_pair_passes`, with OCR faked to return `ABC1O3` against the claim `ABC103`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Inject the detector and OCR callables for tests.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: stage 3 plate match and advisory colour`.

### Task 16: Engine orchestrator

**Files:**
- Create: `backend/core/pipeline.py`, `tests/core/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass(frozen=True) class VerifyInput(request_id: str, driver_id: str, consent_at: datetime, consent_policy_version: str, claimed: Claimed, image_bytes: dict[str, bytes], payload_sha256: str)`
  - `class Engine` with `__init__(settings, registry, store, liveness, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc))` and `verify(inp: VerifyInput) -> dict`.
  - `build_engine(settings: Settings) -> Engine`. It verifies `models.lock`, loads the registry, builds `LocalStore(settings.storage_root, Cipher(...))`, and picks `OnnxLiveness` when `settings.liveness_model` is set, else `DevSkipLiveness` (allowed only when `dev_skip_liveness` is true, which Settings already restricts to dev). When `DevSkipLiveness` is active, every response carries advisory `LIVENESS_SKIPPED_DEV`. The returned dict matches the spec 2.2 JSON exactly: keys `request_id, decision, reasons[{code, retryable, message}], stages{barcode, face, vehicle}{ran, ...details}, advisories, timings_ms, rss_mb, audit{manifest_id, key_id}`.
- Flow:
  1. `lookup` idempotency (a stored response returns immediately; a conflict re-raises).
  2. Open a `SessionWriter`, `put` the originals as raw bytes.
  3. Decode all four images. An `InputError` re-raises and the session stays uncommitted.
  4. Stage 1. On any reason, skip stages 2 and 3.
  5. Stages 2 and 3.
  6. Decide: `APPROVED` iff all three ran and no reasons.
  7. `put` crops (WebP 90) and compressed images (selfie 80, licence 70, vehicle 85).
  8. `commit` the record, which holds the barcode fields, claimed data, consent, decision, reasons, details and timings.
  9. `save` idempotency.
  10. `finally: trim_heap()`.
  Any exception other than `InputError` or `IdempotencyConflict` becomes `EngineError("ENGINE_ERROR")`, and no decision is returned.

- [ ] **Step 1: Write failing tests with fake stages injected.**
  - `test_all_pass_approved_and_session_verifies`
  - `test_stage1_fail_skips_others`
  - `test_stage2_and_3_failures_reported_together`
  - `test_stage_crash_raises_engine_error_never_approved`: the face stage raises `RuntimeError`.
  - `test_storage_failure_raises_engine_error`
  - `test_idempotent_replay_returns_same_response_without_running_stages`
  - `test_conflict_on_changed_payload`
  - `test_input_error_leaves_session_uncommitted`
  - `test_crash_after_originals_then_retry_same_id_succeeds` (Review Focus 5)
  - `test_response_and_logs_contain_no_pii`: use `caplog` and assert that the claimed name, licence number and plate never appear in the logs. The response may contain only `plate_read`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: fail-closed verification engine`.

### Task 17: Evaluation harness

**Files:**
- Create: `scripts/evaluate.py`, `tests/scripts/test_evaluate_stats.py`

**Interfaces:**
- Consumes: Stage 2 functions, `read_plate`, `decode_pdf417`, `parse_aamva`.
- Produces:
  - The CLI `evaluate.py face|liveness|plate|barcode --manifest <csv> --out docs/calibration/<name>.md`.
  - CSV formats:
    - face: `selfie,licence,same_person,person_id,age_gap_years`
    - liveness: `image,is_attack`
    - plate: `image,plate`
    - barcode: `image,province`
  - `clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]`, using `scipy.stats.beta`.
  - `split_by_person(rows, holdout_fraction=0.3) -> tuple[list, list]`, a deterministic split by `sha256(person_id)`.
  - `pick_threshold(genuine: list[float], impostor: list[float], target_far: float) -> float`: the lowest threshold whose FAR on the tuning split is ≤ target.
- Reports show counts, rates with 95% intervals, the chosen threshold, per-age-gap buckets (0–9, 10–19, 20+ years) and an explicit line naming any target the data size cannot prove (for example "FAR ≤ 0.01% needs ≥ 29,956 impostor trials; have N").

- [ ] **Step 1: Write failing tests.**
  - `clopper_pearson(0, 100)` upper bound ≈ 0.0362 (±1e-3).
  - `clopper_pearson(5, 100)` contains 0.05.
  - `split_by_person` never puts one person in both splits.
  - `pick_threshold([0.6, 0.7], [0.1, 0.2, 0.45], 0.0)` returns a value > 0.45.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: evaluation harness with confidence intervals`.

### Task 18: REST API

**Files:**
- Create: `backend/app/main.py`, `backend/app/routes.py`, `backend/app/schemas.py`, `backend/app/security.py`, `backend/app/gate.py`, `tests/app/test_api.py`

**Interfaces:**
- Consumes: `Engine`, `Settings`, `sweep`.
- Produces:
  - `create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI`. Its lifespan loads the registry, builds the engine, and starts a daemon sweeper thread every `sweep_interval_s` (one sweep at startup).
  - `class RunGate` with `try_acquire() -> bool` and `release() -> None`, built on `threading.Lock`.
  - `require_api_key(x_api_key: str | None = Header(None))`, which uses `hmac.compare_digest` and returns `401` with `{"error": {"code": "UNAUTHORIZED"}}`.
  - Routes: `POST /v1/verify`, `GET /v1/sessions/{request_id}`, `GET /health` (no auth; returns `{"status", "models_loaded", "rss_mb"}` and no secrets), and `GET /`.
  - Multipart field names follow spec 2.1 exactly (`claimed.full_name` and so on), through `Form(alias=...)`.
  - The payload hash is the SHA-256 over sorted field names and values plus every file's bytes in `IMAGE_KEYS` order.
  - Errors are always `{"error": {"code": str, "message": str}}`:
    - `422`: `MISSING_FIELD`, `INVALID_FIELD`, `CONSENT_REQUIRED`, `INVALID_IMAGE`, `IMAGE_TOO_LARGE`, plus a custom `RequestValidationError` handler.
    - `409`: `REQUEST_ID_CONFLICT`.
    - `503`: `BUSY` with the `Retry-After` header.
    - `500`: `ENGINE_ERROR`.
  - The verify route is a plain `def` (thread pool). Each upload is read with `file.read(max_upload_bytes + 1)`, and a longer read gives `IMAGE_TOO_LARGE`.

- [ ] **Step 1: Write failing tests with `TestClient` and a fake engine.**
  - `test_missing_key_401`, `test_wrong_key_401`
  - `test_missing_consent_422`
  - `test_bad_province_422`
  - `test_nf_accepted_as_nl`
  - `test_oversize_upload_422`
  - `test_random_bytes_image_422` (Review Focus 1)
  - `test_busy_returns_503_with_retry_after`: hold the gate from another thread through an `Event`.
  - `test_conflict_409`
  - `test_engine_error_500_has_no_decision_key`
  - `test_health_no_secrets`: assert that the API key string is absent.
  - `test_index_served`
  - `test_request_id_rejects_path_chars`: `../x` gives `422`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: REST API with run gate and error mapping`.

### Task 19: Test page

**Files:**
- Create: `backend/static/index.html`, `tests/app/test_page.py`

**Interfaces:**
- Consumes: the route contract from Task 18.
- The page is one file with no external URLs. It has:
  - A form with all `claimed.*` fields (province as a `<select>` of the 13 codes), the two consent fields (consent pre-filled to now) and four `<input type="file" accept="image/*">`.
  - An API key input, kept in `sessionStorage` inside try/catch.
  - A submit button that builds `FormData` and `fetch`es `/v1/verify` with `X-API-Key`.
  - A result panel showing the decision, each reason's message with a "retake" tag when retryable, advisories and timings, plus a `<details>` block with the raw JSON.
  - Labels on every input. Works at 360 px width. Text set with `textContent`, never `innerHTML`.

- [ ] **Step 1: Write failing tests.**
  - `test_page_has_no_external_urls`: no `http://` or `https://` in the file.
  - `test_page_has_all_contract_fields`: every multipart name from Task 18 appears as a `name=` attribute.
  - `test_page_uses_textcontent_not_innerhtml`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS. Then run `uvicorn backend.app.main:app --workers 1`, open `http://127.0.0.1:8000/`, submit one sample set, and check that the result renders.
- [ ] **Step 5: Commit** `feat: single-file test page`.

### Task 20: Real-sample end-to-end check

**Files:**
- Create: `tests/e2e/test_samples.py` (marker `samples`)

**Interfaces:**
- Consumes: `create_app` with the real engine, and `$KOMUTE_SAMPLES_DIR/cases.csv` with columns `case_id,expected_decision,expected_codes,selfie,licence_front,licence_back,vehicle,full_name,date_of_birth,licence_number,issuing_province,plate_number,vehicle_colour`.

- [ ] **Step 1: Write `test_case_matches_expectation`,** parametrised over `cases.csv`. It asserts the decision equals `expected_decision` and the reason codes equal `expected_codes`. After each case it runs `verify_session` and asserts `signature_ok` and an empty `mismatched` list.
- [ ] **Step 2: Run it.** `"$PY" -m pytest tests/e2e -v -m samples`. Expected: PASS for every case. Each failure is a bug to fix in the owning task, not a test to edit, unless the owner confirms the expectation was wrong.
- [ ] **Step 3: Fill the class and restriction tables** in `policy.py` from the samples' `DCA` and `DCB` values, with the owner confirming each code. Add a test per filled jurisdiction in `tests/core/test_gates.py`.
- [ ] **Step 4: Commit** `test: real-sample end-to-end cases`.

### Task 21: Memory, latency and the Linux container

**Files:**
- Create: `scripts/bench.py`, `Dockerfile`, `.dockerignore`, `tests/perf/test_memory.py` (markers `models` and `samples`)

**Interfaces:**
- `bench.py --cases cases.csv --runs 50` runs the engine in-process. A sampler thread reads `rss_mb()` every 5 ms. It prints and writes `docs/calibration/bench.md` with steady RSS (the median after warm-up), peak RSS, and p50 and p95 latency per stage and in total.
- `Dockerfile`: `python:3.12-slim`, `pip install -r requirements.lock`, a non-root user, `ENV MALLOC_ARENA_MAX=2 KOMUTE_ENV=production KOMUTE_STORAGE_ROOT=/var/lib/komute`, the code and models copied in, `/var/lib/komute` as a volume owned by that user, and `CMD uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Samples and keys are never copied into the image.

- [ ] **Step 1: Write `test_rss_bounded_over_50_runs`.** It asserts that steady RSS is ≤ 900 MB, that peak is ≤ 1200 MB, and that RSS after run 50 minus RSS after run 5 is < 50 MB (no leak).
- [ ] **Step 2: Run it on Windows.** Expected: PASS or a clear number. Windows numbers are informational only.
- [ ] **Step 3: Build and run in Linux.** `docker build -t komute-local .`, then run the bench inside with `docker run --memory=1300m --cpus=2 -v "$KOMUTE_SAMPLES_DIR:/samples:ro" --env-file "$LOCALAPPDATA/komute/dev.env" komute-local python scripts/bench.py --cases /samples/cases.csv --runs 50`. Until the owner supplies the liveness model, add `-e KOMUTE_ENV=dev -e KOMUTE_DEV_SKIP_LIVENESS=true`, and note in `bench.md` that the liveness model's memory is not included. Expected: steady ≤ 900 MB, peak ≤ 1200 MB, no OOM kill.
- [ ] **Step 4: If over budget,** measure first with `measure_models.py`, then try in this order: ORT arena flags, a lower `max_image_side`, the variant megapixel cap, and int8 YuNet. Re-run Step 3 after each change. Record every change and its effect in `bench.md`.
- [ ] **Step 5: Commit** `perf: memory bench and Linux container`.

### Task 22: Calibration, documentation and acceptance

**Files:**
- Create: `docs/ACCEPTANCE_REPORT.md`, `docs/calibration/*.md` (from `evaluate.py`)
- Modify: `README.md`, `docs/ARCHITECTURE.md`, `docs/MODELS_SPECIFICATION.md`, `docs/STAGE2_BIOMETRICS_SPECIFICATION.md`, `docs/STAGE3_ALPR_SPECIFICATION.md`, `docs/DEPLOYMENT_AND_OPERATIONS.md`, `docs/STORAGE_SPECIFICATION.md`, `docs/FRONTEND_ELEMENTS_SPECIFICATION.md`, `CLAUDE.md`

- [ ] **Step 1: Run `evaluate.py`** for face, liveness, plate and barcode on the owner's data plus licensed public sets. Set `KOMUTE_FACE_MATCH_THRESHOLD` and `KOMUTE_LIVENESS_THRESHOLD` from the reports and update the defaults in `config.py`.
- [ ] **Step 2: Rewrite `README.md`** to match the code: the real commands, endpoints, contract, measured RAM and latency, and the honest liveness limits. Remove the claims that are not true: "<650 MB", "120–160 ms", "AdaFace", "98.05%", "36-class", "MiVOLO" and "zero-PII".
- [ ] **Step 3: Update each `docs/*.md` file** to the built design. Delete sections that describe removed features (age estimation, composite score, manual review, OCR fallback).
- [ ] **Step 4: Write `docs/ACCEPTANCE_REPORT.md`** with one row per spec section 11 gate: the gate, the measured result, the evidence file, and PASS, FAIL or NOT MEASURED. Name every gate that the data size cannot prove.
- [ ] **Step 5: Run the full suite.** `"$PY" -m pytest -v` (with samples present). Expected: all pass. Paste the summary line into the report.
- [ ] **Step 6: Update `CLAUDE.md`** "Current state", "Commands" and "Known gaps" to the built reality.
- [ ] **Step 7: Commit** `docs: acceptance report and docs matched to code`.

---

## Self-review notes

- **Spec coverage:** contract (Tasks 2, 16, 18), layout (all), data flow (16), stages (8–15), memory (2, 10, 21), storage (4–6), errors (3, 16, 18), page (19), testing (every task, plus 17, 20 and 21), acceptance gates (22), milestones (task order), assumptions (spec deltas). Retention runs in-process (Task 18 lifespan). Manifest key rotation is carried by `key_id` (Task 5).
- **Owner inputs that gate tasks:** the liveness model file (Task 13 `OnnxLiveness` facts, and production start), the sample licences (Tasks 12–15 `samples` tests, Task 20) and labelled pairs (Task 22). Everything else runs without them.
- **What this plan cannot promise:** no plan guarantees zero bugs. It makes every requirement a test, makes every fault fail closed, and makes the acceptance report state measured facts only.
