# Stage 2: Face match and liveness

Code: `backend/core/stages/face.py`, `backend/core/liveness.py`. Runs only when Stage 1 passed.

## Flow

1. **Detect** faces with YuNet (OpenCV `FaceDetectorYN`, input scaled to at most 640 px on the long side).
2. **Pick** the face. Licence front: the largest face (many licences carry a small ghost portrait). Selfie: the largest face; no face gives `FACE_NOT_FOUND_SELFIE` (retryable), and a second strong face (score ≥ 0.9, area ≥ 25% of the largest) gives `IMAGE_QUALITY` (retryable).
3. **Liveness** on the selfie, before any matching. Below the threshold gives `LIVENESS_FAILED` (retryable). A missing licence face gives `FACE_NOT_FOUND_LICENCE` (retryable). These reasons are reported together, and the heavy embedding step is skipped.
4. **Align** both faces to 112×112 with a 5-point similarity transform (InsightFace reference landmarks).
5. **Embed** with `w600k_r50` (RGB, `(x−127.5)/127.5`, 512-d, L2-normalised) and compare by cosine similarity.
6. Below the threshold gives `FACE_MISMATCH` (final). The default threshold, 0.40, is **provisional**. It has not been calibrated (see the acceptance report).

There is no age estimation. Identity rests on the face match and the barcode date of birth.

## Liveness: what it is and what it cannot do

- The selfie is one photo, so liveness is single-frame and passive. It can miss a good screen replay or a high-quality print. Multi-frame or active-challenge liveness would be stronger but needs more than one frame from the host app.
- No liveness model ships in the repo. `OnnxLiveness` (crop, resize, softmax) is built and unit-tested with a fake session. Its crop scale, input size and live-class index default to MiniFASNet-style values and **must be confirmed against the owner's model file**.
- Development can set `KOMUTE_DEV_SKIP_LIVENESS=true`. Every response then carries advisory `LIVENESS_SKIPPED_DEV`, and settings refuse that flag when `KOMUTE_ENV=production`. Production also requires a liveness model path.
- The host app should force a live camera capture and block gallery uploads, and may bind each capture to a one-time token. The module does not do either.

## Measured on real data (see `docs/ACCEPTANCE_REPORT.md`)

Face detection found a face on the licence front of all three real cards. Six impostor pairs (different real people) scored between −0.098 and 0.064; the same photo matched itself at 1.0. Six impostor pairs is far too few to set a threshold.
