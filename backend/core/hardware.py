"""Thread clamps, ORT session options, memory probes. cv2/ort imported lazily."""
from __future__ import annotations

import ctypes
import os
import sys


_PIXEL_LIMIT = 40_000_000
_CLAMP_MSG = "OPENCV_IO_MAX_IMAGE_PIXELS clamp inactive: import backend.core before cv2"


def _check_preset_pixel_limit() -> None:
    raw = os.environ.get("OPENCV_IO_MAX_IMAGE_PIXELS")
    if raw is None:
        return
    try:
        ok = int(raw) <= _PIXEL_LIMIT
    except ValueError:
        ok = False
    if not ok:
        raise RuntimeError(_CLAMP_MSG)


def _probe_pixel_clamp(cv2) -> None:
    """Fail closed: a (limit+1)-pixel PNG must be refused by this OpenCV build."""
    import struct
    import zlib

    import numpy as np

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    w = h = int(_PIXEL_LIMIT**0.5) + 1  # w*h > limit; libpng caps width, so not 1 row
    z = zlib.compressobj()
    row = bytes(w + 1)
    idat = b"".join(z.compress(row) for _ in range(h)) + z.flush()
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    try:
        cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return
    raise RuntimeError(_CLAMP_MSG)  # decoded or silently failed: the clamp is not provably active


def apply_env_clamps() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "2")
    os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "1")
    _check_preset_pixel_limit()
    os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(_PIXEL_LIMIT))
    _clamp_cv2()


def _clamp_cv2() -> None:
    import cv2  # imported only after the env vars are set

    cv2.setNumThreads(2)
    _probe_pixel_clamp(cv2)


def ort_session_options():
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False  # Task 21 may flip these using measurements
    so.enable_mem_pattern = False
    return so


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1_048_576


def trim_heap() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # non-glibc libc (musl): nothing to trim
