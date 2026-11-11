import os
from pathlib import Path

import numpy as np
import pytest

import backend.core  # noqa: F401  (clamps before cv2)
import cv2

from backend.core.contracts import EngineError, Reason, ReasonCode
from backend.core.stages.face import (
    REFERENCE_112,
    FaceBox,
    FaceDetector,
    align_112,
    alignment_matrix,
    pick_licence_face,
    pick_selfie_face,
)

YUNET = Path("backend/models/face_detection_yunet_2023mar.onnx")


def box(score, w, h=None):
    h = h or w
    return FaceBox(score, (0, 0, w, h), np.zeros((5, 2), np.float32))


def test_alignment_maps_reference_points_to_themselves():
    lm = REFERENCE_112 * 3 + 10
    m = alignment_matrix(lm)
    mapped = cv2.transform(lm.reshape(1, 5, 2), m).reshape(5, 2)
    assert np.abs(mapped - REFERENCE_112).max() < 1.0


def test_align_112_output_shape():
    img = np.zeros((336, 336, 3), np.uint8)
    assert align_112(img, REFERENCE_112 * 3).shape == (112, 112, 3)


def test_degenerate_landmarks_raise_engine_error():
    with pytest.raises(EngineError):
        alignment_matrix(np.zeros((5, 2), np.float32))


def test_pick_licence_face_takes_largest_ignores_ghost():
    small, large = box(0.99, 30), box(0.8, 120)
    assert pick_licence_face([small, large]) is large
    assert pick_licence_face([]) is None


def test_selfie_second_strong_face_is_image_quality():
    r = pick_selfie_face([box(0.99, 200), box(0.95, 120)])
    assert isinstance(r, Reason) and r.code == ReasonCode.IMAGE_QUALITY and r.retryable


def test_selfie_small_background_face_ignored():
    main = box(0.99, 200)
    assert pick_selfie_face([main, box(0.95, 40)]) is main
    assert pick_selfie_face([main, box(0.6, 190)]) is main


def test_selfie_no_face():
    r = pick_selfie_face([])
    assert r.code == ReasonCode.FACE_NOT_FOUND_SELFIE and r.retryable


@pytest.mark.models
def test_detector_runs_on_blank_image_returns_empty():
    assert FaceDetector(YUNET).detect(np.full((480, 640, 3), 128, np.uint8)) == []


def _sample_images():
    root = os.environ.get("KOMUTE_SAMPLES_DIR", "")
    return sorted(Path(root, "raw").glob("p*/*")) if root else []


@pytest.mark.samples
@pytest.mark.models
def test_detector_finds_a_face_on_one_side_of_each_real_licence():
    det = FaceDetector(YUNET)
    by_person: dict[str, int] = {}
    for path in _sample_images():
        img = cv2.imread(str(path))
        assert img is not None
        by_person[path.parent.name] = by_person.get(path.parent.name, 0) + len(det.detect(img))
    assert by_person and all(count >= 1 for count in by_person.values())  # counts only, no values printed
