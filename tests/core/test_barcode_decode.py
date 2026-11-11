import time
import tracemalloc

import numpy as np
import pytest

import backend.core  # noqa: F401  (must precede cv2)
import cv2

from backend.core.aamva import parse_aamva
from backend.core.policy import IIN_TO_PROVINCE
from backend.core.stages.barcode import decode_pdf417, iter_variants
from tests.fixtures.aamva_factory import make_aamva_text, render_card, distort

DISTORTIONS = ["blur", "rotate90", "perspective", "dark", "small"]


@pytest.mark.parametrize("iin", sorted(IIN_TO_PROVINCE))
@pytest.mark.parametrize("kind", ["none"] + DISTORTIONS)
def test_decodes_synthetic_card(iin, kind):
    text = make_aamva_text(iin=iin)
    img = render_card(text)
    if kind != "none":
        img = distort(img, kind)
    rec = parse_aamva(decode_pdf417(img))
    assert rec is not None and rec.iin == iin


def test_returns_none_for_blank_card():
    assert decode_pdf417(np.full((600, 900, 3), 200, np.uint8), budget_s=5) is None


def test_ignores_code128_decoy_only():
    import zxingcpp

    img = np.full((400, 800), 255, np.uint8)
    bar = np.array(zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("1462949", zxingcpp.BarcodeFormat.Code128), scale=3))
    img[50 : 50 + bar.shape[0], 50 : 50 + bar.shape[1]] = bar
    assert decode_pdf417(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), budget_s=5) is None


def test_empty_input_returns_none():
    assert decode_pdf417(np.zeros((0, 0, 3), np.uint8)) is None
    assert decode_pdf417(None) is None


def test_budget_stops_the_search():
    t = time.monotonic()
    assert decode_pdf417(np.random.default_rng(0).integers(0, 255, (1500, 2000, 3), dtype=np.uint8), budget_s=0.01) is None
    assert time.monotonic() - t < 20


def test_variants_are_lazy_and_skip_oversize():
    gray = np.zeros((2048, 1536), np.uint8)
    it = iter_variants(gray)
    first = next(it)
    assert first.shape == gray.shape
    sizes = [v.size for v in it]
    assert max(sizes) <= 25_000_000 and len(sizes) >= 10


def test_peak_python_memory_bounded_for_large_card():
    img = render_card(make_aamva_text(), canvas=(1536, 2048))
    blank = np.full((1536, 2048, 3), 200, np.uint8)
    tracemalloc.start()
    decode_pdf417(img)
    decode_pdf417(blank, budget_s=2)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 250 * 1024 * 1024
