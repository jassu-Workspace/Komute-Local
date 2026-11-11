import json
from pathlib import Path

import numpy as np
import pytest

import backend.core  # noqa: F401
import cv2

from backend.core.registry import ModelRegistry
from backend.core.stages.vehicle import (
    PAD,
    PLATE_ALPHABET,
    PlateBox,
    crop_with_margin,
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


def _slots(text, p=0.99, overrides=None):
    """A fake model output [1, 10, 37]: each slot puts probability p on its character (pad after the text)."""
    out = np.full((1, 10, 37), (1 - p) / 36)
    for i in range(10):
        out[0, i, PLATE_ALPHABET.index(text[i]) if i < len(text) else PAD] = p
    for (slot, char), prob in (overrides or {}).items():
        out[0, slot, :] = (1 - prob) / 36
        out[0, slot, PLATE_ALPHABET.index(char)] = prob
    return out


class FakeOcr:
    def __init__(self, output):
        self.output, self.fed = output, None

    def run(self, names, feed):
        self.fed = (names, feed)
        return [self.output]


def test_read_plate_decodes_slots_and_drops_pads():
    text, conf = read_plate(np.zeros((40, 80, 3), np.uint8), FakeOcr(_slots("ABC123", 0.97)))
    assert text == "ABC123" and conf == pytest.approx(0.97)


def test_read_plate_keeps_double_letters_in_separate_slots():
    assert read_plate(np.zeros((40, 80, 3), np.uint8), FakeOcr(_slots("AAA0000")))[0] == "AAA0000"


def test_read_plate_confidence_is_the_weakest_slot_not_the_average():
    ocr = FakeOcr(_slots("ABC123", 0.999, {(4, "2"): 0.55}))
    text, conf = read_plate(np.zeros((40, 80, 3), np.uint8), ocr)
    assert text == "ABC123" and conf == pytest.approx(0.55)


def test_read_plate_all_pad_is_empty_and_a_middle_pad_is_dropped():
    assert read_plate(np.zeros((40, 80, 3), np.uint8), FakeOcr(_slots("")))[0] == ""
    assert read_plate(np.zeros((40, 80, 3), np.uint8), FakeOcr(_slots("ABC", 0.99, {(1, "_"): 0.99})))[0] == "AC"


def test_read_plate_feeds_rgb_uint8_nhwc_128x64():
    ocr = FakeOcr(_slots("AB"))
    bgr = np.zeros((50, 100, 3), np.uint8)
    bgr[..., 0] = 10  # blue channel in BGR
    bgr[..., 2] = 200  # red channel in BGR
    read_plate(bgr, ocr)
    names, feed = ocr.fed
    x = feed["input"]
    assert names == ["plate"] and x.shape == (1, 64, 128, 3) and x.dtype == np.uint8
    assert x[0, 0, 0, 0] == 200 and x[0, 0, 0, 2] == 10  # RGB order: red first


def test_alphabet_matches_the_model_card():
    assert len(PLATE_ALPHABET) == 37 and PLATE_ALPHABET[PAD] == "_" and PLATE_ALPHABET[:10] == "0123456789"


def _plate_image(text="ABC123", w=256, h=128):
    img = np.full((h, w, 3), 255, np.uint8)
    cv2.putText(img, text, (14, 84), cv2.FONT_HERSHEY_DUPLEX, 1.9, (0, 0, 0), 3, cv2.LINE_AA)
    return img


@pytest.mark.models
def test_reads_rendered_plate(reg):
    text, conf = read_plate(_plate_image(), reg.session("plate_ocr"))
    assert text == "ABC123" and 0.5 < conf <= 1.0


@pytest.mark.models
def test_detects_synthetic_plate(reg):
    img = cv2.imread(str(FIX / "synthetic_vehicle.png"))
    box = detect_plate(img, reg.session("plate_detector"))
    assert box is not None and abs(box.x1 - 490) < 15 and abs(box.y1 - 440) < 15


@pytest.mark.models
def test_no_plate_on_blank_scene(reg):
    assert detect_plate(np.full((720, 1280, 3), 128, np.uint8), reg.session("plate_detector")) is None


def test_empty_crop_reads_nothing():
    assert read_plate(np.zeros((0, 0, 3), np.uint8), None) == ("", 0.0)


def test_crop_with_margin_clipped_to_image():
    img = np.zeros((100, 200, 3), np.uint8)
    crop = crop_with_margin(img, PlateBox(0, 0, 100, 50, 0.9))
    assert crop.shape[0] <= 54 and crop.shape[1] <= 108
