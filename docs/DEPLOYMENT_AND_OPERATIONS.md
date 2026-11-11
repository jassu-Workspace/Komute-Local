# Deployment & Operations Runbook — Komüte-Local

> **Production deployment configurations, containerization, CPU thread clamping, memory monitoring, telemetry endpoints, and operational troubleshooting.**

---

## 1. Production Deployment Topology

Komüte-Local is designed to run as a stateless microservice behind any L7 load balancer (e.g., NGINX, Cloudflare, Traefik, or AWS ALB).

```
                      INTERNET / INGRESS
                               │
                               ▼
                 NGINX / Cloudflare Reverse Proxy
                 (SSL Termination, DDoS, Rate Limit)
                               │
                               ▼
             Komüte-Local Container (Uvicorn / Gunicorn)
             ├── Hardware Thread Clamping (2 CPU Workers)
             ├── Resident Memory Operating Envelope (346 MB - 1230 MB RAM)
             └── Local Persistent Storage (/storage/sessions)
```

---

## 2. Docker Containerization (Zero-PyTorch Slim Build)

Because all inference runs via `onnxruntime` and `opencv-python-headless`, the production Docker image is under **500 MB** (compared to 4.5+ GB for PyTorch images):

```dockerfile
# Multi-stage minimal production Dockerfile
FROM python:3.11-slim AS builder

WORKDIR /app

# Install native build tools for zxing-cpp and opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY backend/ ./backend/

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=2
ENV ORT_INTRA_OP_NUM_THREADS=2
ENV ORT_INTER_OP_NUM_THREADS=1

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

---

## 3. Environment Variable Configuration (`.env`)

```ini
# Application Core
APP_NAME="Komute-Local Verification Node"
APP_VERSION="2.0.0"
ENVIRONMENT="production"
PORT=8000

# Hardware & Thread Governance (Clamped at 2 Threads)
OMP_NUM_THREADS=2
OPENBLAS_NUM_THREADS=2
MKL_NUM_THREADS=2
ORT_INTRA_OP_NUM_THREADS=2
ORT_INTER_OP_NUM_THREADS=1

# Security & Rate Limiting
API_SECRET_KEY="km_live_secure_production_key_here"
RATE_LIMIT_PER_MINUTE=60

# Verification Threshold Gates
COMPOSITE_APPROVAL_THRESHOLD=0.80
CROSS_AGE_SIMILARITY_THRESHOLD=0.40
PLATE_MATCH_THRESHOLD=0.85
AGE_MINIMUM_YEARS=18.0

# Storage Retention
STORAGE_ROOT="backend/storage/sessions"
RETAIN_REJECTED_IMAGES=false
```

---

## 4. Health Checks & Telemetry Endpoints

The service exposes diagnostic endpoints for load balancers and monitoring dashboards:

### 4.1 Shallow Liveness Probe
* **Endpoint**: `GET /ping`
* **Response**: `{"status": "pong", "timestamp": "2026-11-11T07:00:00Z"}`
* **Use Case**: Kubernetes / Docker swarm container health checks.

### 4.2 Deep Readiness Probe
* **Endpoint**: `GET /health`
* **Verification**: Checks that all 5 ONNX model files in `backend/models/` exist and are initialized in RAM.
* **Response**:
  ```json
  {
    "status": "healthy",
    "models_loaded": {
      "face_detector_yunet": true,
      "face_verifier_arcface": true,
      "face_age_genderage": true,
      "plate_detector_yolo": true,
      "plate_recognizer_ocr": true
    },
    "memory_rss_mb": 594.4
  }
  ```

---

## 5. Offline Profiling & Benchmark Execution

To evaluate accuracy, latency, and memory consumption against sample credentials without spinning up the network server, use the standalone benchmark suite:

```powershell
python "temporary/benchmark_runner.py" `
  --front "path/to/front.jpeg" `
  --back "path/to/back.jpeg" `
  --selfie "path/to/selfie.jpeg" `
  --vehicle "path/to/vehicle.webp"
```

* **Outputs Generated**:
  1. `temporary/benchmark_results.json`: Full machine-readable verification metrics, structured AAMVA fields, and 1ms memory profiling timeline.
  2. `temporary/dashboard.html`: Fluid responsive dashboard containing 3-column categorized license tables, micro-latency tables, and the CIELAB color swatch.

---

## 6. Troubleshooting & Operational Runbook

### Issue 1: Memory RSS Peaks at ~850 MB During Stage 1
* **Root Cause**: The AAMVA engine executes a multi-variant 19-pass scanning strategy, generating up to 19 uncompressed bitmap variations in memory concurrently (including $1.6\times$ and $2.5\times$ upscaled images for module resolution).
* **Operational Status**: **Expected and Safe**. The 853 MB peak is well within the 1,300 MB hardware envelope ceiling. The OS heap allocator (`ntdll` / `ucrtbase` Low Fragmentation Heap) retains these pages in the committed working set, preventing subsequent stages from needing to allocate new virtual memory.

### Issue 2: AAMVA Barcode Fails to Decode on License Back
* **Root Cause**: Smartphone capture is vertically oriented, blurry, or captured under extreme low light.
* **Resolution**:
  1. Verify that `_generate_variants` generates $-90^\circ$ and $+90^\circ$ rotations.
  2. Ensure the persistent PDF417 search loop does not terminate early if a 1D Code 128 / Code 39 barcode is detected first.
  3. Validate that CLAHE contrast and sharpness enhancements are enabled on the grayscale variant.

### Issue 3: Vehicle Exterior Color Misclassified as Blue on Dark Gray / Charcoal Cars
* **Root Cause**: Brittle HSV thresholds misinterpreting ambient blue sky reflections on horizontal car surfaces.
* **Resolution**:
  1. Ensure the engine uses **CIE $L^*a^*b^*$ $\Delta E$ Distance** rather than HSV boundaries.
  2. Confirm that contextual sheet-metal patches directly adjacent to the plate are being isolated rather than the full vehicle bounding box (which captures tinted glass and shadows).
  3. Verify specular glare filtering ($L^* > 92$) and cavity shadow filtering ($L^* < 8$) are active.

### Issue 4: Cross-Age False Rejections on 30+ Year Age Gaps
* **Root Cause**: Cosine similarity hovering around $0.37 – 0.39$.
* **Resolution**:
  1. Confirm facial crops were aligned using 5-point canonical affine landmarks (Umeyama algorithm to $112 \times 112$).
  2. Verify that `CROSS_AGE_SIMILARITY_THRESHOLD` is configured to `0.40` (the calibrated cross-age threshold for 10–40 year spans).
