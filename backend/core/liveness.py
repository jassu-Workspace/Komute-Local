"""Single-photo passive liveness. The model file is supplied by the owner (none ships in the repo)."""
from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

from .stages.face import FaceBox


class LivenessModel(Protocol):
    def score(self, img_bgr: np.ndarray, face: FaceBox) -> float:
        """Probability in [0, 1] that the face is a live person."""


class DevSkipLiveness:
    """Dev only. Settings refuse it in production; every response carries advisory LIVENESS_SKIPPED_DEV."""

    def score(self, img_bgr: np.ndarray, face: FaceBox) -> float:
        return 1.0


class OnnxLiveness:
    """Passive anti-spoof classifier (MiniFASNet style): crop around the face, resize, softmax.

    `crop_scale`, `input_size` and `live_index` come from the model's facts once the file arrives.
    """

    def __init__(self, session, crop_scale: float, input_size: int, live_index: int) -> None:
        self._session = session
        self._input = session.get_inputs()[0].name
        self._scale = crop_scale
        self._size = input_size
        self._live = live_index

    def _crop(self, img: np.ndarray, face: FaceBox) -> np.ndarray:
        x, y, w, h = face.box
        side = max(w, h) * self._scale
        cx, cy = x + w / 2, y + h / 2
        x1, y1 = int(round(cx - side / 2)), int(round(cy - side / 2))
        x2, y2 = int(round(cx + side / 2)), int(round(cy + side / 2))
        pad = max(0, -x1, -y1, x2 - img.shape[1], y2 - img.shape[0])
        if pad:
            img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
            x1, y1, x2, y2 = x1 + pad, y1 + pad, x2 + pad, y2 + pad
        return cv2.resize(img[y1:y2, x1:x2], (self._size, self._size), interpolation=cv2.INTER_LINEAR)

    def score(self, img_bgr: np.ndarray, face: FaceBox) -> float:
        blob = self._crop(img_bgr, face).astype(np.float32).transpose(2, 0, 1)[None]
        logits = np.asarray(self._session.run(None, {self._input: blob})[0], dtype=np.float64).reshape(-1)
        e = np.exp(logits - logits.max())
        return float((e / e.sum())[self._live])
