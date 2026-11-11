# Models

The authoritative measured facts (tensor shapes, memory, latency, class counts, SHA-256) are in `docs/MODEL_FACTS.md`. `backend/models/models.lock` pins the SHA-256 of every file the engine loads. **The engine refuses to start if a locked file is missing, changed or absent from the lock.**

| Role | File | Used |
|---|---|---|
| Face detection and 5 landmarks | `face_detection_yunet_2023mar.onnx` | yes (OpenCV `FaceDetectorYN`) |
| Face embedding, 512-d | `w600k_r50.onnx` | yes. Threshold still provisional |
| Plate detection | `yolo-v9-t-384-license-plates-end2end.onnx` | yes. NMS is inside the graph |
| Plate OCR | `plate_ocr_ppocrv5_mobile.onnx` + `plate_ocr_dict.json` | yes. 18,385 classes, output masked to `A–Z`, `0–9` |
| Liveness | none in the repo | the owner supplies it; required in production |
| Age estimation | `genderage.onnx`, `mivolo_v2_age.onnx` | **no**. Dropped; not locked, not loaded, not shipped in the container |

Earlier versions of this document claimed AdaFace, a 36-class OCR and MiVOLO v2 as active. None of those is true of the built system.

To replace a model: copy the new file into `backend/models/`, run `python scripts/measure_models.py` (it rewrites `models.lock` and the facts table), re-check the preprocessing in `docs/MODEL_FACTS.md`, and recalibrate any threshold that depends on it. Embeddings from different face models are not interchangeable.
