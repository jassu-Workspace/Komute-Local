"""Thread clamps, ORT session options, memory probes. cv2/ort imported lazily."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time


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


class MemorySampler:
    """Samples this process's RSS on a background thread while a verification runs."""

    def __init__(self, interval_s: float = 0.05, max_points: int = 240) -> None:
        self._interval, self._max = interval_s, max_points
        self._points: list[tuple[float, float]] = []
        self._marks: list[tuple[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def _now_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)

    def __enter__(self) -> "MemorySampler":
        self._t0 = time.perf_counter()
        self._points.append((0.0, round(rss_mb(), 1)))
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._points.append((self._now_ms(), round(rss_mb(), 1)))

    def mark(self, name: str) -> None:
        self._marks.append((name, self._now_ms()))

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._points.append((self._now_ms(), round(rss_mb(), 1)))

    def trace(self) -> dict:
        pts = self._points
        if len(pts) > self._max:  # keep the first, the last and the peak; thin the rest evenly
            step = len(pts) / self._max
            keep = {int(i * step) for i in range(self._max)} | {0, len(pts) - 1, max(range(len(pts)), key=lambda i: pts[i][1])}
            pts = [pts[i] for i in sorted(keep)]
        return {
            "start_mb": pts[0][1], "end_mb": pts[-1][1], "peak_mb": max(p[1] for p in pts),
            "points": [[t, mb] for t, mb in pts], "marks": [[n, t] for n, t in self._marks],
        }


def trim_heap() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # non-glibc libc (musl): nothing to trim
