from datetime import date
from types import SimpleNamespace

import numpy as np

import backend.core  # noqa: F401
import cv2

from backend.core.contracts import Advisory, Claimed, ReasonCode
from backend.core.stages.vehicle import (
    PlateBox,
    claimed_colour_family,
    classify_colour,
    run_vehicle_stage,
)

SETTINGS = SimpleNamespace(plate_min_confidence=0.6)
BOX = PlateBox(400, 300, 600, 360, 0.9)


def scene(bgr, w=1000, h=700):
    img = np.full((h, w, 3), bgr, np.uint8)
    img[BOX.y1 : BOX.y2, BOX.x1 : BOX.x2] = 255
    return img


def claimed(colour="Red", plate="ABC123"):
    return Claimed("A B", date(1990, 1, 1), "X", "ON", plate, colour)


def test_solid_red_body_is_red():
    assert classify_colour(scene((27, 27, 179)), BOX).name == "Red"


def test_white_body_is_white_not_filtered_as_glare():
    r = classify_colour(scene((248, 246, 245)), BOX)
    assert r is not None and r.name == "White"


def test_dark_body_is_black_or_graphite_not_blue():
    r = classify_colour(scene((40, 36, 36)), BOX)
    assert r.name in ("Black", "Dark Charcoal / Graphite")


def test_pure_glare_pixels_are_filtered():
    img = np.full((700, 1000, 3), 255, np.uint8)
    assert classify_colour(img, BOX) is None


def test_patch_outside_image_returns_none():
    assert classify_colour(np.zeros((10, 10, 3), np.uint8), PlateBox(2000, 2000, 2100, 2050, 0.9)) is None


def test_claimed_colour_families():
    assert claimed_colour_family("Dark Grey") == {"Grey", "Dark Charcoal / Graphite"}
    assert claimed_colour_family("light blue") == {"Light Blue"}
    assert claimed_colour_family("Rainbow") is None


def run(read=("ABC123", 0.95), detect=BOX, colour="Red", plate="ABC123", img=None):
    return run_vehicle_stage(
        scene((27, 27, 179)) if img is None else img, claimed(colour, plate), lambda i: detect, lambda c: read, SETTINGS
    )


def test_plate_match_passes_and_colour_match_has_no_advisory():
    r = run()
    assert r.reasons == [] and r.advisories == [] and r.details["plate_matched"]
    assert r.crops["plate"].size > 0 and r.details["colour"] == "Red"


def test_colour_mismatch_is_advisory_not_reason():
    r = run(colour="Blue")
    assert r.reasons == [] and r.advisories == [Advisory.COLOUR_MISMATCH]


def test_unknown_claimed_colour_unverified():
    assert run(colour="Rainbow").advisories == [Advisory.COLOUR_UNVERIFIED]


def test_plate_missing_gives_retryable():
    r = run(detect=None)
    assert [x.code for x in r.reasons] == [ReasonCode.PLATE_NOT_FOUND] and r.reasons[0].retryable
    assert r.crops == {}


def test_low_confidence_read_is_retryable_unreadable_not_mismatch():
    r = run(read=("XYZ999", 0.3))
    assert [x.code for x in r.reasons] == [ReasonCode.PLATE_UNREADABLE] and r.reasons[0].retryable


def test_empty_read_is_unreadable():
    assert run(read=("", 0.0)).reasons[0].code == ReasonCode.PLATE_UNREADABLE


def test_plate_mismatch_is_final():
    r = run(read=("ABK123", 0.95))
    assert [x.code for x in r.reasons] == [ReasonCode.PLATE_MISMATCH] and not r.reasons[0].retryable


def test_plate_confusion_pair_passes():
    assert run(read=("ABC1O3", 0.95), plate="ABC103").reasons == []
