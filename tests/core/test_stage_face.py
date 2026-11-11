import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import backend.core  # noqa: F401
from backend.core.contracts import EngineError, ReasonCode
from backend.core.liveness import DevSkipLiveness, OnnxLiveness
from backend.core.registry import ModelRegistry
from backend.core.stages.face import REFERENCE_112, FaceBox, cosine, embed, run_face_stage

SETTINGS = SimpleNamespace(face_match_threshold=0.40, liveness_threshold=0.5)
IMG = np.full((300, 300, 3), 120, np.uint8)


def face(score=0.99, size=100):
    return FaceBox(score, (50, 50, size, size), REFERENCE_112 * 2.5)


class Detector:
    def __init__(self, selfie_faces, licence_faces):
        self._queue = [selfie_faces, licence_faces]

    def detect(self, img):
        return self._queue.pop(0)


class Live:
    def __init__(self, s):
        self.s = s

    def score(self, img, f):
        return self.s


def vec(i):
    v = np.zeros(512)
    v[i] = 1.0
    return v


def test_cosine_identical_is_one_and_orthogonal_zero():
    assert cosine(vec(1), vec(1)) == pytest.approx(1.0)
    assert cosine(vec(1), vec(2)) == pytest.approx(0.0)


def test_liveness_fail_short_circuits_match():
    calls = []
    r = run_face_stage(IMG, IMG, Detector([face()], [face()]), lambda c: calls.append(1) or vec(0), Live(0.1), SETTINGS)
    assert [x.code for x in r.reasons] == [ReasonCode.LIVENESS_FAILED] and r.reasons[0].retryable
    assert calls == []


def test_no_faces_reported_together():
    r = run_face_stage(IMG, IMG, Detector([], []), lambda c: vec(0), Live(1.0), SETTINGS)
    assert {x.code for x in r.reasons} == {ReasonCode.FACE_NOT_FOUND_SELFIE, ReasonCode.FACE_NOT_FOUND_LICENCE}


def test_mismatch():
    vecs = iter([vec(1), vec(2)])
    r = run_face_stage(IMG, IMG, Detector([face()], [face()]), lambda c: next(vecs), Live(0.9), SETTINGS)
    assert [x.code for x in r.reasons] == [ReasonCode.FACE_MISMATCH] and not r.reasons[0].retryable
    assert r.details["similarity"] == pytest.approx(0.0)


def test_match_and_crops():
    r = run_face_stage(IMG, IMG, Detector([face()], [face()]), lambda c: vec(3), Live(0.9), SETTINGS)
    assert r.reasons == [] and r.details["similarity"] == pytest.approx(1.0)
    assert set(r.crops) == {"selfie_face", "licence_face"} and r.crops["selfie_face"].shape == (112, 112, 3)


def test_dev_skip_liveness_scores_one():
    assert DevSkipLiveness().score(IMG, face()) == 1.0


class FakeSession:
    def __init__(self, logits):
        self.logits, self.seen = logits, None

    def get_inputs(self):
        return [SimpleNamespace(name="x")]

    def run(self, _, feed):
        self.seen = feed["x"]
        return [np.array([self.logits])]


def test_onnx_liveness_softmax_and_input_shape():
    s = FakeSession([0.0, 2.0, 0.0])
    p = OnnxLiveness(s, crop_scale=2.0, input_size=80, live_index=1).score(IMG, face())
    assert 0.78 < p < 0.79 and s.seen.shape == (1, 3, 80, 80) and s.seen.dtype == np.float32


def test_onnx_liveness_face_near_border_does_not_crash():
    s = FakeSession([1.0, 1.0])
    edge = FaceBox(0.99, (0, 0, 120, 120), REFERENCE_112)
    assert OnnxLiveness(s, 4.0, 80, 0).score(IMG, edge) == pytest.approx(0.5)


@pytest.mark.models
def test_embed_shape_and_unit_norm():
    reg = ModelRegistry(Path("backend/models"), Path("backend/models/models.lock"), None)
    reg.load()
    out = embed(np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8), reg.session("face_embedder"))
    assert out.shape == (512,) and abs(np.linalg.norm(out) - 1.0) < 1e-4


def test_embed_zero_vector_guard():
    class Zero(FakeSession):
        def run(self, _, feed):
            return [np.zeros((1, 512))]

    with pytest.raises(EngineError):
        embed(np.zeros((112, 112, 3), np.uint8), Zero([0]))


@pytest.mark.samples
def test_same_person_pairs_listed_in_pairs_csv_are_informational():
    csv = Path(os.environ.get("KOMUTE_SAMPLES_DIR", ""), "pairs.csv")
    if not csv.exists():
        pytest.skip("no pairs.csv yet: owner selfies not supplied")
