"""Trust boundary for uploaded images: every failure becomes InputError."""
import cv2
import numpy as np

from backend.core.contracts import InputError

IMAGE_KEYS = ("selfie", "licence_front", "licence_back", "vehicle")


def decode_image(data: bytes, max_side: int) -> np.ndarray:
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) == 0:
        raise InputError("INVALID_IMAGE")
    try:
        # IMREAD_COLOR applies EXIF orientation and forces 3-channel BGR uint8.
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            raise InputError("INVALID_IMAGE")
        h, w = img.shape[:2]
        long_side = max(h, w)
        if long_side > max_side:
            s = max_side / long_side
            img = cv2.resize(
                img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA
            )
        return img
    except (cv2.error, MemoryError, ValueError) as e:
        raise InputError("INVALID_IMAGE") from e


def encode_webp(img: np.ndarray, quality: int) -> bytes:
    if not isinstance(img, np.ndarray) or img.size == 0:
        raise InputError("INVALID_IMAGE")
    try:
        ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, int(quality)])
    except cv2.error as e:
        raise InputError("INVALID_IMAGE") from e
    if not ok:
        raise InputError("INVALID_IMAGE")
    return buf.tobytes()
