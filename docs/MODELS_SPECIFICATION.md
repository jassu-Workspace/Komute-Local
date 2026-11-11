# Models Specification & Registry — Komüte-Local

> **Complete architectural profiles, tensor input/output signatures, memory envelopes, quantization procedures, and official sources for all local ONNX neural network models and classical vision algorithms.**

---

## 1. Master Model Registry

All neural models are executed locally using `onnxruntime.InferenceSession` with the standard CPU Execution Provider (`CPUExecutionProvider`) clamped to 2 hardware threads.

| # | Model Identifier / File | Task / Stage | Architecture | Parameters | Disk Size | RAM Footprint | Input Shape | Output Shape | Latency (2 Threads) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M1** | `face_detection_yunet_2023mar.onnx` | Stage 2A: Face & Landmark Isolation | YuNet CNN | ~0.85M | ~1.1 MB | **~25 MB** | `[1, 3, 320, 320]` (Dynamic) | `[N, 15]` (BBox + 5 Landmarks + Score) | **~6 to 18 ms** |
| **M2** | `w600k_r50.onnx` / `adaface_ir50.onnx` | Stage 2B: Cross-Age Face Verification | IResNet-50 (ArcFace/AdaFace) | ~43.6M | ~165 MB | **~210 MB** | `[1, 3, 112, 112]` | `[1, 512]` (L2-Normalized Embedding) | **~160 ms** |
| **M3** | `genderage.onnx` / `mivolo_v2.onnx` | Stage 2C: Facial Age & Gap Estimation | MobileNet / Vision Transformer | ~2.5M | ~9.2 MB | **~45 MB** | `[1, 3, 96, 96]` or `[1, 3, 224, 224]` | `[1, 3]` (Sex + Age Scalar) | **~1.7 to 50 ms** |
| **M4** | `yolov9_tiny_plate.onnx` | Stage 3A: License Plate Detection | YOLOv9-Tiny (Single-Class) | ~2.1M | ~6.2 MB | **~35 MB** | `[1, 3, 384, 384]` | `[1, 5, 3024]` (BBox + Conf) | **~12 to 14 ms** |
| **M5** | `ch_PP-OCRv5_rec.onnx` / `cct_xs.onnx` | Stage 3B: Plate Alphanumeric OCR | Mobile Conv-Transformer | ~3.2M | ~11.5 MB | **~40 MB** | `[1, 3, 48, W]` (Dynamic W) | `[1, T, 37]` (37-Class CTC Probabilities) | **~8 to 10 ms** |
| **C1** | `CIELAB_Delta_E_Classifier` | Stage 3C: Vehicle Paint Classification | Analytical CIE $L^*a^*b^*$ | N/A | N/A | **~5 MB** | 4 Sheet-Metal BGR Crops | Name, Hex, CIELAB $\Delta E$ Distance | **~0.15 ms** |
| — | **Total Model Suite** | **End-to-End Autonomous Engine** | **Heterogeneous AI Suite** | **~52.2M** | **~193 MB** | **~360 MB (Net)** | — | — | **~280 to 450 ms** |

---

## 2. Model Deep-Dive Specifications

### 2.1 Model M1: YuNet Face & Landmark Detector
* **Role**: Detects faces in driver license photos and live selfies; extracts the 5 primary cranial landmarks (right eye, left eye, nose tip, right mouth corner, left mouth corner).
* **Preprocessing**:
  * Format: BGR uint8 NumPy array.
  * Resized dynamically with aspect ratio preservation (standard $320 \times 320$ or native scale).
* **Output Format**:
  * Tensor of shape `[N, 15]`:
    * Indices `0..3`: Bounding box `[x, y, w, h]`
    * Indices `4..5`: Right Eye `[x, y]`
    * Indices `6..7`: Left Eye `[x, y]`
    * Indices `8..9`: Nose Tip `[x, y]`
    * Indices `10..11`: Right Mouth Corner `[x, y]`
    * Indices `12..13`: Left Mouth Corner `[x, y]`
    * Index `14`: Detection confidence score $[0.0, 1.0]$

---

### 2.2 Model M2: ArcFace w600k_r50 / AdaFace IR-50 (Cross-Age Face Verification)
* **Role**: Extracts an invariant 512-dimensional facial embedding resistant to aging variations (10 to 40-year spans), weight changes, facial hair, and scan degradation.
* **Preprocessing**:
  * Input dimensions: Exactly $112 \times 112 \times 3$ pixels.
  * Transformation: Canonical 5-point affine similarity alignment (Umeyama algorithm).
  * Color space: BGR $\rightarrow$ RGB.
  * Normalization: Pixel values normalized via `(img / 127.5) - 1.0` (range $[-1.0, 1.0]$).
  * Layout: `NCHW` float32 tensor of shape `[1, 3, 112, 112]`.
* **Output**:
  * Embedding vector $\mathbf{v} \in \mathbb{R}^{512}$.
  * L2-normalized: $\hat{\mathbf{v}} = \frac{\mathbf{v}}{\|\mathbf{v}\|_2}$.
* **Cross-Age Matching Equation**:
  $$\text{Cosine Similarity} = \hat{\mathbf{v}}_{\text{selfie}} \cdot \hat{\mathbf{v}}_{\text{DL}}$$
  * Decision Gate: $\text{Cosine Similarity} \ge 0.40 \implies \text{MATCH\_CONFIRMED}$.

---

### 2.3 Model M3: GenderAge / MiVOLO v2 (Continuous Age Estimation)
* **Role**: Predicts continuous apparent age from the facial crop. Used to compute $\Delta\text{Age} = |\text{Age}_{\text{selfie}} - \text{Age}_{\text{DL}}|$.
* **Preprocessing**:
  * Input dimensions: $96 \times 96 \times 3$ (GenderAge) or $224 \times 224 \times 3$ (MiVOLO v2).
  * Normalization: Scaled to $[-1.0, 1.0]$ or ImageNet standard normal distribution.
  * Layout: `NCHW` float32 tensor.
* **Output**:
  * Scalar representing estimated chronological age in years (e.g. `24.5` vs `28.2`).
  * Cross-checked against the barcode's date of birth (`DBB`) and card issue date (`DBD`).

---

### 2.4 Model M4: YOLOv9-Tiny License Plate Detector
* **Role**: Isolates vehicle license plate bounding polygons from full vehicle exterior photos.
* **Preprocessing**:
  * Input dimensions: $384 \times 384 \times 3$.
  * Normalization: Scaled to $[0.0, 1.0]$ (`img / 255.0`).
  * Layout: `NCHW` float32 tensor of shape `[1, 3, 384, 384]`.
* **Output**:
  * Tensor of candidate bounding boxes: `[x, y, w, h, confidence]`.
  * Non-Maximum Suppression (NMS) threshold: `IoU = 0.45`, `Score = 0.35`.

---

### 2.5 Model M5: PP-OCRv5 Mobile / CCT-XS Plate CTC Character Recognizer
* **Role**: Reads the alphanumeric license plate string from the cropped plate image.
* **Vocabulary (37 Classes)**:
  * Index `0`: CTC Blank token (`<blank>`)
  * Indices `1..10`: Digits `0` through `9`
  * Indices `11..36`: Uppercase Latin letters `A` through `Z`
  * Total output classes: Exactly 37 (Zero risk of outputting Chinese, punctuation, or obscure symbols).
* **Preprocessing**:
  * Dynamic height scaling to 48px height with aspect-ratio preserving width $W$.
  * Layout: `NCHW` float32 tensor of shape `[1, 3, 48, W]`.
* **Output**:
  * Tensor of shape `[1, T, 37]`: $T$ time-steps, each outputting a 37-class probability distribution.
  * Greedy CTC Best-Path Decoding: Argmax selection collapsing repeating consecutive tokens and eliminating blanks.

---

### 2.6 Algorithm C1: Automotive CIELAB $\Delta E$ Color Classifier
* **Role**: Classifies the true exterior body paint color of the vehicle using perceptually uniform color science.
* **Input**: 4 contextual sheet-metal patches cropped immediately above, below, left, and right of the detected license plate bounding box.
* **Luminance Filtering**: Filters specular glare ($L^* > 92$) and cavity shadows ($L^* < 8$).
* **Mathematical Metric**: CIE76 Euclidean color distance against calibrated OEM automotive standards:
  $$\Delta E = \sqrt{(L_1^* - L_2^*)^2 + (a_1^* - a_2^*)^2 + (b_1^* - b_2^*)^2}$$
* **Output**: Dominant color name (e.g. `Dark Charcoal / Graphite`), color hex code (`#2e2e33`), and minimum $\Delta E$ distance.

---

## 3. Official Model Sources & Checksums

| Model | Official Origin / Repository | Architecture | Direct Reference Link |
| :--- | :--- | :--- | :--- |
| **YuNet** | OpenCV Zoo Official | YuNet CNN | [opencv/opencv_zoo (YuNet)](https://github.com/opencv/opencv_zoo/tree/master/models/face_detection_yunet) |
| **ArcFace w600k** | InsightFace Official Model Zoo | IResNet-50 | [deepinsight/insightface](https://github.com/deepinsight/insightface) |
| **AdaFace IR-50** | Minchul Kim et al. (CVPR 2022) | IResNet-50 | [mk-minchul/AdaFace](https://github.com/mk-minchul/adaface) |
| **GenderAge** | InsightFace MobileNet | MobileNet-V2 | [deepinsight/insightface](https://github.com/deepinsight/insightface) |
| **YOLOv9-Tiny Plate** | Andrew Ank (Fast-ALPR) | YOLOv9-Tiny | [GitHub: ankandrew/fast-alpr](https://github.com/ankandrew/fast-alpr) |
| **PP-OCRv5 Mobile** | PaddleOCR Global / Fast-Plate | Conv-Transformer | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) |
