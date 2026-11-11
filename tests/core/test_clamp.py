import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MSG = "OPENCV_IO_MAX_IMAGE_PIXELS clamp inactive"


def _run(code: str, **env):
    e = {k: v for k, v in os.environ.items() if k != "OPENCV_IO_MAX_IMAGE_PIXELS"}
    e.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True)


def test_cv2_imported_first_fails_closed():
    r = _run("import cv2; import backend.core")
    assert r.returncode != 0 and MSG in r.stderr


def test_preset_larger_limit_fails_closed():
    r = _run("import backend.core", OPENCV_IO_MAX_IMAGE_PIXELS="999999999")
    assert r.returncode != 0 and MSG in r.stderr


def test_normal_import_succeeds():
    r = _run("import backend.core")
    assert r.returncode == 0, r.stderr
