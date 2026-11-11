"""Regression guard on real internet photos of Canadian plates (kept outside the repo: watermarked stock images).

Needs $KOMUTE_SAMPLES_DIR/plates/truth.csv (columns file,plate) and the image files.
Baseline with cct-xs-v2-global: 9 of 9 plates read exactly, every character at 0.99 or better.
"""
import csv
import os
from pathlib import Path

import numpy as np
import pytest

import backend.core  # noqa: F401
import cv2

from backend.core.matching import plates_match
from backend.core.registry import ModelRegistry
from backend.core.stages.vehicle import crop_with_margin, detect_plate, read_plate

pytestmark = [pytest.mark.samples, pytest.mark.models]


@pytest.fixture(scope="module")
def reads():
    folder = Path(os.environ["KOMUTE_SAMPLES_DIR"], "plates")
    if not (folder / "truth.csv").exists():
        pytest.skip("no plate photos supplied")
    reg = ModelRegistry(Path("backend/models"), Path("backend/models/models.lock"), None)
    reg.load()
    out = []
    for r in csv.DictReader(open(folder / "truth.csv", encoding="utf-8")):
        img = cv2.imdecode(np.fromfile(str(folder / r["file"]), np.uint8), cv2.IMREAD_COLOR)
        box = detect_plate(img, reg.session("plate_detector"))
        assert box is not None, f"plate not found in {r['file']}"
        text, conf = read_plate(crop_with_margin(img, box), reg.session("plate_ocr"))
        out.append((r["plate"], text, conf))
    return out


def test_every_plate_is_read_exactly_and_confidently(reads):
    assert [(t, r) for t, r, _ in reads if t != r] == []
    assert min(c for _, _, c in reads) >= 0.9


def test_the_true_plate_matches_and_every_other_plate_does_not(reads):
    for truth, text, _ in reads:
        assert plates_match(text, truth)
        assert not any(plates_match(text, other) for other, _, _ in reads if other != truth)
