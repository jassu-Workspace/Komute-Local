import json
from pathlib import Path

import numpy as np
import pytest

import backend.core  # noqa: F401
import cv2

from backend.core.registry import ModelRegistry
from backend.core.stages.vehicle import (
    PlateBox,
    allowed_indices,
    crop_with_margin,
    ctc_decode,
    decode_end2end,
    detect_plate,
    letterbox,
    read_plate,
)

FIX = Path("tests/fixtures")


@pytest.fixture(scope="module")
def reg():
    r = ModelRegistry(Path("backend/models"), Path("backend/models/models.lock"), None)
    r.load()
    return r


def small_charset():
    # blank, '口' (CJK), 'A', 'B', '1', ' ' (space last)
    return ["", "口", "A", "B", "1", " "]


def test_letterbox_roundtrip_coordinates():
    img = np.zeros((720, 1280, 3), np.uint8)
    tensor, scale, pad = letterbox(img)
    assert tensor.shape == (1, 3, 384, 384) and tensor.dtype == np.float32
    assert scale == pytest.approx(0.3) and pad == (0, 84)
    out = np.array([[0, 100 * scale + pad[0], 200 * scale + pad[1], 400 * scale + pad[0], 300 * scale + pad[1], 0, 0.9]])
    [b] = decode_end2end(out, scale, pad)
    assert max(abs(b.x1 - 100), abs(b.y1 - 200), abs(b.x2 - 400), abs(b.y2 - 300)) <= 1


def test_decode_end2end_filters_low_scores():
    out = np.array([[0, 10, 10, 50, 40, 0, 0.04], [0, 10, 10, 50, 40, 0, 0.67]])
    assert [round(b.score, 2) for b in decode_end2end(out, 1.0, (0, 0))] == [0.67]


def test_decode_end2end_on_recorded_fixture():
    out = np.load(FIX / "yolo_output.npy")
    meta = json.loads((FIX / "yolo_output.json").read_text())
    boxes = decode_end2end(out, meta["scale"], tuple(meta["pad"]))
    assert boxes
    best = max(boxes, key=lambda b: b.score)
    assert abs(best.x1 - meta["box"][0]) <= 2 and abs(best.y2 - meta["box"][3]) <= 2


def test_ctc_masked_decode_ignores_cjk_columns():
    cs = small_charset()
    allowed = allowed_indices(cs)
    assert list(allowed) == [0, 2, 3, 4]
    probs = np.array([
        [0.05, 0.80, 0.10, 0.03, 0.01, 0.01],  # CJK dominates -> best plate char is 'A'
        [0.90, 0.02, 0.03, 0.02, 0.02, 0.01],  # blank
        [0.05, 0.05, 0.05, 0.80, 0.03, 0.02],  # 'B'
    ])
    assert ctc_decode(probs, cs, allowed)[0] == "AB"


def test_ctc_collapses_repeats_and_blank_separates_doubles():
    cs = small_charset()
    allowed = allowed_indices(cs)

    def row(i):
        r = np.full(6, 0.01)
        r[i] = 0.95
        return r

    assert ctc_decode(np.array([row(2), row(2), row(3)]), cs, allowed)[0] == "AB"
    assert ctc_decode(np.array([row(2), row(0), row(2)]), cs, allowed)[0] == "AA"
    assert ctc_decode(np.array([row(5), row(0)]), cs, allowed) == ("", 0.0)


def test_allowed_indices_match_measured_charset(reg):
    allowed = allowed_indices(reg.plate_charset)
    assert len(allowed) == 37 and allowed[0] == 0
    assert reg.plate_charset[16163] == "0" and reg.plate_charset[16179] == "A"


def _plate_image(text="ABC123", w=300, h=100):
    img = np.full((h, w, 3), 255, np.uint8)
    cv2.putText(img, text, (12, 72), cv2.FONT_HERSHEY_DUPLEX, 2.0, (0, 0, 0), 3, cv2.LINE_AA)
    return img


@pytest.mark.models
def test_reads_rendered_plate(reg):
    allowed = allowed_indices(reg.plate_charset)
    text, conf = read_plate(_plate_image(), reg.session("plate_ocr"), reg.plate_charset, allowed)
    assert text == "ABC123" and 0 < conf <= 1.0


@pytest.mark.models
def test_detects_synthetic_plate(reg):
    img = cv2.imread(str(FIX / "synthetic_vehicle.png"))
    box = detect_plate(img, reg.session("plate_detector"))
    assert box is not None and abs(box.x1 - 490) < 15 and abs(box.y1 - 440) < 15


@pytest.mark.models
def test_no_plate_on_blank_scene(reg):
    assert detect_plate(np.full((720, 1280, 3), 128, np.uint8), reg.session("plate_detector")) is None


def test_empty_crop_reads_nothing():
    assert read_plate(np.zeros((0, 0, 3), np.uint8), None, small_charset(), np.array([0])) == ("", 0.0)


def test_crop_with_margin_clipped_to_image():
    img = np.zeros((100, 200, 3), np.uint8)
    crop = crop_with_margin(img, PlateBox(0, 0, 100, 50, 0.9))
    assert crop.shape[0] <= 54 and crop.shape[1] <= 108
