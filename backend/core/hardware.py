"""Thread clamps, ORT session options, memory probes. cv2/ort imported lazily."""
from __future__ import annotations

import ctypes
import os
import sys


def apply_env_clamps() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "2")
    os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "1")
    os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000")
    _clamp_cv2()


def _clamp_cv2() -> None:
    import cv2  # imported only after the env vars are set

    cv2.setNumThreads(2)


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
