"""Stage 2: face detection, selection and alignment (embedding and liveness are added in Task 13)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np

from ..contracts import EngineError, Reason, ReasonCode

# InsightFace 112x112 reference landmarks: left eye, right eye, nose, left mouth, right mouth (image order).
REFERENCE_112 = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)
DETECT_MAX_SIDE = 640


@dataclass(frozen=True, eq=False)
class FaceBox:
    score: float
    box: tuple[int, int, int, int]  # x, y, w, h in original pixels
    landmarks: np.ndarray  # (5, 2) float32 in original pixels

    @property
    def area(self) -> int:
        return self.box[2] * self.box[3]


class FaceDetector:
    def __init__(self, model_path: Path, score_threshold: float = 0.7) -> None:
        self._det = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold, 0.3, 50)

    def detect(self, img_bgr: np.ndarray) -> list[FaceBox]:
        h, w = img_bgr.shape[:2]
        scale = min(1.0, DETECT_MAX_SIDE / max(h, w))
        small = img_bgr if scale == 1.0 else cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        self._det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self._det.detect(small)
        if faces is None:
            return []
        out = []
        for f in faces:
            lm = (f[4:14].reshape(5, 2) / scale).astype(np.float32)
            x, y, bw, bh = (f[0:4] / scale)
            out.append(FaceBox(float(f[14]), (int(x), int(y), int(bw), int(bh)), lm))
        return out


def alignment_matrix(landmarks: np.ndarray) -> np.ndarray:
    m, _ = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), REFERENCE_112, method=cv2.LMEDS)
    if m is None:
        raise EngineError("ALIGN_FAILED")
    return m


def align_112(img_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    return cv2.warpAffine(img_bgr, alignment_matrix(landmarks), (112, 112), borderValue=(0, 0, 0))


def pick_licence_face(faces: list[FaceBox]) -> Optional[FaceBox]:
    """The largest face: licences often carry a small ghost portrait as well."""
    return max(faces, key=lambda f: f.area) if faces else None


def pick_selfie_face(faces: list[FaceBox]) -> Union[FaceBox, Reason]:
    if not faces:
        return Reason.of(ReasonCode.FACE_NOT_FOUND_SELFIE)
    ranked = sorted(faces, key=lambda f: f.area, reverse=True)
    if len(ranked) > 1 and ranked[1].score >= 0.9 and ranked[1].area >= 0.25 * ranked[0].area:
        return Reason.of(ReasonCode.IMAGE_QUALITY)
    return ranked[0]
