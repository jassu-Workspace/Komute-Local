"""Stage 1: find and decode the AAMVA PDF417 on the licence back.

Image variants are generated one at a time and freed before the next one is built.
"""
from __future__ import annotations

import time
from typing import Callable, Iterator, Optional

import cv2
import numpy as np
import zxingcpp

MAX_VARIANT_PIXELS = 25_000_000
DEFAULT_BUDGET_S = 10.0


def _sharpen(g: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(g, (0, 0), 2.0)
    return cv2.addWeighted(g, 2.0, blur, -1.0, 0)


def _otsu(g: np.ndarray) -> np.ndarray:
    return cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def _scale(g: np.ndarray, f: float) -> np.ndarray:
    return cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)


def iter_variants(gray: np.ndarray) -> Iterator[np.ndarray]:
    """Yield grayscale uint8 variants lazily. Variants over 25 megapixels are skipped."""
    h, w = gray.shape
    hh, hw = h // 2, w // 2
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    # (pixel factor relative to the original, builder)
    recipes: list[tuple[float, Callable[[], np.ndarray]]] = [
        (1.0, lambda: gray),
        (1.6**2, lambda: _scale(gray, 1.6)),
        (2.5**2, lambda: _scale(gray, 2.5)),
        (1.0, lambda: _sharpen(gray)),
        (1.0, lambda: clahe.apply(gray)),
        (1.0, lambda: _otsu(gray)),
        (1.8**2, lambda: _otsu(_scale(gray, 1.8))),
        (1.0, lambda: cv2.bitwise_not(gray)),
        (1.0, lambda: cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        (1.0, lambda: cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)),
        (0.25, lambda: gray[:hh, :hw]),
        (0.25, lambda: gray[:hh, hw:]),
        (0.25, lambda: gray[hh:, :hw]),
        (0.25, lambda: gray[hh:, hw:]),
        (0.5, lambda: gray[:hh, :]),
        (0.5, lambda: gray[hh:, :]),
        (2.0, lambda: _scale(gray[:hh, :], 2.0)),
        (2.0, lambda: _scale(gray[hh:, :], 2.0)),
    ]
    for factor, build in recipes:
        if h * w * factor > MAX_VARIANT_PIXELS:
            continue
        variant = build()
        yield variant
        del variant


def decode_pdf417(img_bgr: np.ndarray, budget_s: float = DEFAULT_BUDGET_S) -> Optional[str]:
    """Return the first PDF417 payload as latin-1 text, or None. Gives up after `budget_s` seconds."""
    if img_bgr is None or img_bgr.size == 0:
        return None
    gray = img_bgr if img_bgr.ndim == 2 else cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    deadline = time.monotonic() + budget_s
    for variant in iter_variants(gray):
        for binarizer in (zxingcpp.Binarizer.LocalAverage, zxingcpp.Binarizer.GlobalHistogram):
            found = zxingcpp.read_barcodes(
                variant,
                formats=zxingcpp.BarcodeFormat.PDF417,
                try_rotate=True,
                try_downscale=True,
                try_invert=True,
                text_mode=zxingcpp.TextMode.Plain,
                binarizer=binarizer,
            )
            if found:
                return found[0].bytes.decode("latin-1")
        if time.monotonic() > deadline:
            return None
    return None
