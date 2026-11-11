# Architecture — Komüte-Local v2

> **System design, pipeline flow, component responsibilities, micro-latency profiling, and resource-bounded execution governance for production engineers and maintainers.**

---

## 1. System Purpose & Core Philosophy

**Komüte-Local** is a mission-critical identity and vehicle verification engine designed for driver onboarding. It evaluates three foundational questions in a single automated pass:

1. **Who is the applicant?** Verified deterministically via the government-issued 2D AAMVA PDF417 barcode on the reverse of the driver's license card, parsed across standard and provincial subfiles into 6 canonical categories.
2. **Is the person presenting the application the legitimate holder?** Verified biometrically by isolating facial portraits, extracting 512-dimensional cranial embeddings via deep metric architectures (**AdaFace IR-50** / **ArcFace w600k_r50**) across **10 to 40-year age gaps**, and estimating the continuous facial age delta ($\Delta\text{Age}$) via **GenderAge / MiVOLO v2**.
3. **Is the vehicle registered and legitimate?** Verified through dedicated neural license plate detection (**YOLOv9-Tiny**), 36-class alphanumeric CTC character reading (**PP-OCRv5 / CCT-XS**), and contextual sheet-metal exterior paint classification via **Perceptually Uniform CIELAB $\Delta E$ Distance**.

### Foundational Design Decisions

1. **Zero-Cloud & Zero-API Dependency**: All vision, OCR, and biometric models execute locally using **ONNX Runtime** and optimized C++ backends. Eliminates cloud latency (from 20s down to <150ms), eliminates API fees, and prevents 429 rate limit outages.
2. **Zero-PII Leakage**: The driving license card is parsed locally. Face crops are isolated and aligned before feature extraction. No raw documents or unmasked images leave the local process boundary.
3. **Hardware-Clamped Memory Governance**: Enforces execution within a **1.0 to 1.3 GB RAM** cloud container ceiling via 2 clamped CPU threads and intelligent heap reuse.
4. **Deterministic Auditing**: All decoded barcodes, facial embeddings, and plate OCR tokens provide transparent microsecond timing breakdowns and 1ms memory profiling metrics.

---

## 2. High-Level System Architecture & Component Mapping

```
Client App (Komüte Onboarding UI / Backend API / CLI Runner)
        │
        │  POST /api/v1/verify (JSON + base64 images)
        │  X-API-Key + Sliding-Window Rate Limiter
        ▼
FastAPI Server (backend/app/main.py + routes.py)
  ├── schemas.py      — Strict Pydantic v2 request/response contracts
  ├── config.py       — Immutable environment configuration & threshold gates
  ├── security.py     — Constant-time API key auth + in-memory rate limiting
        │
        ▼
VerificationPipeline (backend/core/pipeline.py)
  │
  ├── STAGE 1: dl_barcode.py (ZXing-CPP AAMVA PDF417 Multi-Variant Engine)
  │     ├── 19-Pass Multi-Scale Image Transformation Pipeline (1.6x, 2.5x, Otsu, Crops)
  │     ├── Subfile Directory Parser (_parse_directory): DL & Provincial (ZO) Subfiles
  │     ├── International Date Order Resolver: CAN (CCYYMMDD) vs USA (MMDDCCYY)
  │     └── 6 Canonical Category Segregation: IDENTITY, LICENCE, DATES, ADDRESS, PHYSICAL, CLASS
  │
  ├── STAGE 2: Biometric Verification Engine
  │     ├── Stage 2A: face_cropper.py (YuNet ONNX Landmark Face Isolation + Umeyama 5-Pt Affine)
  │     ├── Stage 2B: face_verifier.py (AdaFace IR-50 / ArcFace w600k 512-d Embedding Verification)
  │     └── Stage 2C: face_age_estimator.py (GenderAge / MiVOLO v2 Continuous Age Delta Estimation)
  │
  ├── STAGE 3: Vehicle ALPR & CIELAB Color Engine
  │     ├── Stage 3A: vehicle_alpr.py (YOLOv9-Tiny 384x384 Single-Class Plate Detector)
  │     ├── Stage 3B: vehicle_ocr.py (PP-OCRv5 Mobile / CCT-XS Dynamic CTC OCR Sequence Decoder)
  │     └── Stage 3C: vehicle_color.py (Contextual Sheet-Metal Patch Isolation + CIELAB ΔE)
  │
  └── SHARED: image_utils.py (SIMD base64 decoding, 5-point affine alignment, WebP)
        │
        ▼  BackgroundTasks (Non-blocking I/O)
StorageManager (backend/storage/storage.py)
  storage/sessions/{driver_id}_{request_id}/
    ├── metadata.json
    ├── dl_face_crop.webp
    └── vehicle_plate_crop.webp
```

---

## 3. Concurrency & Execution Lifecycle

The pipeline executes CPU-bound neural inference and C++ barcode decoding synchronously under strict thread clamps:

```
[Request Ingest]
       │
       ▼
1. Image Normalization & Decoding
   ├── Decode base64 to BGR NumPy arrays
   ├── Flatten license card perspective (if skewed)
   └── Downscale vehicle photo to max 1200px (memory cap)
       │
       ▼
2. Stage 1: Deterministic AAMVA PDF417 Extraction
   ├── Run 19-variant scanning engine across scales (1.6x, 2.5x), rotations, and binarizers
   ├── Parse AAMVA header, IIN, version, and subfile directories (DL, ZO)
   ├── Resolve date wire order based on DCG country (CAN vs USA)
   └── Segregate fields into 6 canonical categories
       │
       ▼
3. Stage 2: Zero-PII Facial Isolation & Cross-Age Biometrics
   ├── YuNet detects driver face on DL front card (5 primary landmarks)
   ├── YuNet detects face on live selfie (5 primary landmarks)
   ├── Umeyama 5-point similarity transform deskews faces to canonical 112×112
   ├── AdaFace IR-50 / ArcFace w600k extracts 512-d normalized cranial embeddings
   ├── Hyperspherical cosine distance verifies cross-age identity
   └── GenderAge / MiVOLO v2 estimates continuous age delta (ΔAge)
       │
       ▼
4. Stage 3: Vehicle ALPR & Automotive Color Classification
   ├── YOLOv9-Tiny detects license plate bounding box at 384×384
   ├── PP-OCRv5 / CCT-XS performs dynamic CTC alphanumeric reading
   ├── Isolates contextual sheet-metal patches adjacent to plate
   └── Matches dominant cluster against OEM automotive palette via CIELAB ΔE
       │
       ▼
5. Composite Decision Formulation & Telemetry Output
   ├── Evaluate Stage 1, Stage 2, and Stage 3 pass criteria
   ├── Compute composite weighted score
   ├── Check hard-rejection triggers (e.g. expired license, under 18, plate mismatch)
   └── Generate real-time 1ms memory profiling and micro-latency telemetry
```

---

## 4. Hardware Clamping & Memory Governance

To ensure the microservice operates reliably within a **1.0 to 1.3 GB container budget**, `backend/core/hardware_profile.py` clamps threading at process boot:

### 4.1 Thread Clamping Configuration
```python
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["ORT_INTRA_OP_NUM_THREADS"] = "2"
os.environ["ORT_INTER_OP_NUM_THREADS"] = "1"
cv2.setNumThreads(2)
```

### 4.2 System Memory Envelope & Profiling Matrix

The table below reflects real-time 1-millisecond memory sampling during production benchmarking:

| Pipeline Stage / Scope | Sub-Task Focus | Latency (ms) | Start RAM | Peak RAM | Micro Surge | Net Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Process Boot** | Python + OpenCV + Runtime | — | 0.0 MB | ~306 MB | — | +306.6 MB |
| **Stage 1** | Barcode Scan & AAMVA Token Parsing | ~91 to 1974 ms | 346.45 MB | 853.63 MB | **+507.18 MB** | +388.48 MB |
| **Stage 2A** | YuNet DL Face & Umeyama Alignment | ~142.42 ms | 345.41 MB | 634.68 MB | +289.27 MB | +240.45 MB |
| **Stage 2B** | ArcFace Cross-Age 512-d Embedding | ~326.88 ms | 1183.70 MB | 1204.91 MB | +21.21 MB | +21.19 MB |
| **Stage 2C** | GenderAge Age & Delta Estimation | ~1.70 ms | 1204.89 MB | 1205.57 MB | +0.68 MB | +0.66 MB |
| **Stage 3A** | YOLOv9-Tiny 384x384 Plate Detector | ~37.46 ms | 1205.55 MB | 1222.64 MB | +17.09 MB | +15.38 MB |
| **Stage 3B** | PP-OCRv5 Mobile Plate CTC Recognizer | ~16.70 ms | 1217.55 MB | 1220.39 MB | +2.84 MB | +4.58 MB |
| **Stage 3C** | Automotive CIELAB Body Paint delta-E | ~147.53 ms | 1222.14 MB | 1232.95 MB | +10.81 MB | +10.85 MB |
| **Total Pipeline** | **End-to-End Verification Pipeline** | **~855 to 2600 ms** | **346 MB** | **1232.95 MB** | **Budget: 1300 MB** | **Safe Operating Envelope** |

### Understanding the Stage 1 +507 MB Surge
* **Cause**: Pre-generating up to 19 uncompressed high-resolution bitmap transformations in RAM (including $2.5\times$ upscaled images) simultaneously with native C++ `BitMatrix` buffers in `zxing-cpp`.
* **Heap Retention**: The operating system memory allocator (`ntdll` / `ucrtbase` Low Fragmentation Heap) marks these freed buffers as available within the process heap, pre-allocating memory for subsequent neural model execution.

---

## 5. Micro-Latency Telemetry Architecture

Every verification run records sub-task micro-latencies down to the millisecond:

```
Stage 2 Biometrics Breakdown:
├── YuNet Face Detection (DL Card):          ~155.0 ms
├── Umeyama 5-Pt Affine Alignment (DL):        ~0.6 ms
├── YuNet Face Detection (Selfie):              ~6.8 ms
├── Umeyama 5-Pt Affine Alignment (Selfie):    ~0.6 ms
├── DL Tensor Preprocessing (112×112):         ~0.3 ms
├── ArcFace w600k_r50 DL Embedding (512-d):  ~162.0 ms
├── Selfie Tensor Preprocess (112×112):        ~0.3 ms
├── ArcFace w600k_r50 Selfie Embedding:      ~162.0 ms
├── Hyperspherical L2 & Cosine Metric:         ~0.1 ms
└── GenderAge Facial Age Delta Estimation:     ~1.7 ms

Stage 3 ALPR Breakdown:
├── YOLOv9-Tiny 384×384 Preprocessing:         ~1.2 ms
├── YOLOv9-Tiny ONNX Forward Inference:       ~12.8 ms
├── Plate BBox Rescaling & Sub-Image Crop:     ~0.4 ms
├── Plate OCR Dynamic 48h Preprocessing:       ~0.6 ms
├── PP-OCRv5 Mobile ONNX Inference:            ~8.9 ms
├── Greedy CTC Character Sequence Decoding:    ~0.2 ms
├── Body Sheet-Metal Patch Isolation:          ~0.3 ms
├── Specular Glare & Shadow Filtering:         ~0.8 ms
├── K-Means (K=3) Color Clustering:            ~3.1 ms
└── Automotive CIELAB Delta-E Classification:  ~0.1 ms
```

---

## 6. Composite Scoring Mathematics & Hard Rejections

The final verification verdict is computed deterministically:

### 6.1 Composite Confidence Formula
$$\text{Composite Score} = (0.30 \cdot S_1) + (0.45 \cdot S_2) + (0.25 \cdot S_3)$$

* **$S_1$ (Stage 1)**: $1.0$ if barcode decoded, name matches, DL matches, age $\ge 18$, not expired; else $0.0$.
* **$S_2$ (Stage 2)**: Scaled cosine similarity score across 10–40 year age gaps ($\text{Threshold} \ge 0.40$).
* **$S_3$ (Stage 3)**: Weighted blend of plate text similarity ($0.75$) and CIELAB color agreement ($0.25$).

### 6.2 Hard Rejection Triggers
An instant `REJECTED` verdict is emitted if any of the following occur:
* `UNDERAGE_DRIVER`: Calculated driver age $< 18.0$ years.
* `EXPIRED_LICENSE`: License expiration date is earlier than the current UTC date.
* `NAME_MISMATCH`: Levenshtein token similarity between applicant name and barcode name $< 0.85$.
* `DL_NUMBER_MISMATCH`: Cleaned license number similarity $< 0.90$.
* `BIOMETRIC_MISMATCH`: Facial cosine similarity $< 0.38$.
* `PLATE_MISMATCH`: Plate character similarity $< 0.85$.
