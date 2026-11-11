"""Measure every ONNX model, write models.lock, print a markdown table, build the YOLO fixture.

Run: python scripts/measure_models.py   (from the repo root, after source scripts/dev_env.sh)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.core.hardware import ort_session_options, rss_mb  # noqa: E402

FACTS_START, FACTS_END = "<!-- facts:start -->", "<!-- facts:end -->"
MODELS = ROOT / "backend" / "models"
LOCK = MODELS / "models.lock"
FIXTURES = ROOT / "tests" / "fixtures"
LOCKED = [
    "face_detection_yunet_2023mar.onnx",
    "w600k_r50.onnx",
    "yolo-v9-t-384-license-plates-end2end.onnx",
    "cct_xs_v2_global.onnx",
]
UNUSED = {"genderage.onnx", "mivolo_v2_age.onnx"}  # measured for the facts table only
DYN = {"yolo-v9-t-384-license-plates-end2end.onnx": {"*": 384}}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def concrete_shape(name: str, shape: list) -> list[int]:
    """Replace dynamic dims. Batch -> 1; spatial dims -> the value from DYN."""
    rule = DYN.get(name, {})
    out = []
    for i, d in enumerate(shape):
        if isinstance(d, int) and d > 0:
            out.append(d)
        elif i == 0:
            out.append(1)
        elif "*" in rule:
            out.append(rule["*"])
        elif i == len(shape) - 1 and "width" in rule:
            out.append(rule["width"])
        else:
            out.append(1)
    return out


NP_DTYPES = {"tensor(float)": np.float32, "tensor(uint8)": np.uint8, "tensor(int64)": np.int64}


def measure(path: Path) -> dict:
    import onnxruntime as ort

    before = rss_mb()
    sess = ort.InferenceSession(str(path), ort_session_options(), providers=["CPUExecutionProvider"])
    after = rss_mb()
    ins = sess.get_inputs()
    feeds = {
        i.name: np.zeros(concrete_shape(path.name, list(i.shape)), NP_DTYPES.get(i.type, np.float32)) for i in ins
    }
    lat = []
    outs = None
    for _ in range(5):
        t = time.perf_counter()
        outs = sess.run(None, feeds)
        lat.append((time.perf_counter() - t) * 1000)
    return {
        "file": path.name,
        "sha256": sha256(path),
        "inputs": [(i.name, i.shape, i.type) for i in ins],
        "outputs": [(o.name, o.shape, o.type) for o in sess.get_outputs()],
        "run_input_shapes": [list(v.shape) for v in feeds.values()],
        "run_output_shapes": [list(o.shape) for o in outs],
        "rss_before": before,
        "rss_after": after,
        "lat_ms": lat,
    }


def table(rows: list[dict]) -> str:
    lines = [
        "| File | SHA-256 | Inputs (name, shape, dtype) | Outputs (name, shape, dtype) | Output shape on test run | RSS before -> after (MB) | Latency 5 runs, ms (min / median) | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lat = sorted(r["lat_ms"])
        status = "unused (age estimation dropped)" if r["file"] in UNUSED else "locked"
        lines.append(
            f"| {r['file']} | `{r['sha256']}` | {r['inputs']} | {r['outputs']} | {r['run_output_shapes']} "
            f"| {r['rss_before']:.0f} -> {r['rss_after']:.0f} | {lat[0]:.1f} / {lat[2]:.1f} | {status} |"
        )
    return "\n".join(lines)


def ocr_facts() -> dict:
    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(MODELS / "cct_xs_v2_global.onnx"), ort_session_options(), providers=["CPUExecutionProvider"]
    )
    plate, region = sess.run(None, {"input": np.zeros((1, 64, 128, 3), np.uint8)})
    return {
        "plate_shape": list(plate.shape),
        "region_shape": list(region.shape),
        "plate_rows_sum_to_one": bool(np.allclose(plate.sum(-1), 1.0, atol=1e-4)),
        "region_sums_to_one": bool(abs(float(region.sum()) - 1.0) < 1e-4),
    }


def letterbox(img: np.ndarray, size: int = 384):
    import cv2

    h, w = img.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = round(w * scale), round(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    padx, pady = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[pady : pady + nh, padx : padx + nw] = resized
    return canvas, scale, (padx, pady)


def yolo_fixture() -> dict:
    """Synthetic scene (no real vehicle photo exists). Saves raw output and the detected box."""
    import cv2
    import onnxruntime as ort

    FIXTURES.mkdir(parents=True, exist_ok=True)
    img = np.full((720, 1280, 3), 128, np.uint8)
    cv2.rectangle(img, (240, 160), (1040, 640), (40, 40, 160), -1)  # car-coloured body (BGR)
    x0, y0 = 490, 440
    cv2.rectangle(img, (x0, y0), (x0 + 300, y0 + 100), (255, 255, 255), -1)
    cv2.putText(img, "ABC123", (x0 + 15, y0 + 70), cv2.FONT_HERSHEY_SIMPLEX, 1.9, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.imwrite(str(FIXTURES / "synthetic_vehicle.png"), img)

    lb, scale, pad = letterbox(img)
    x = (lb[:, :, ::-1].astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    sess = ort.InferenceSession(
        str(MODELS / "yolo-v9-t-384-license-plates-end2end.onnx"),
        ort_session_options(),
        providers=["CPUExecutionProvider"],
    )
    inp = sess.get_inputs()[0]
    raw = sess.run(None, {inp.name: np.ascontiguousarray(x)})[0]
    np.save(FIXTURES / "yolo_output.npy", raw)
    return {"scale": scale, "pad": list(pad), "raw_shape": list(raw.shape), "raw_dtype": str(raw.dtype), "raw": raw}


def main() -> None:
    rows = [measure(p) for p in sorted(MODELS.glob("*.onnx"))]
    lock = {n: sha256(MODELS / n) for n in LOCKED}
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(table(rows))
    facts = ROOT / "docs" / "MODEL_FACTS.md"
    text = facts.read_text(encoding="utf-8")
    a, b = text.index(FACTS_START) + len(FACTS_START), text.index(FACTS_END)
    facts.write_text(text[:a] + "\n\n" + table(rows) + "\n\n" + text[b:], encoding="utf-8")
    print("\nOCR:", json.dumps(ocr_facts()))
    y = yolo_fixture()
    raw = y.pop("raw")
    print("\nYOLO:", json.dumps(y))
    print("raw[0][:5] =", np.round(raw.reshape(-1, raw.shape[-1])[:5], 3).tolist())
    # Layout inferred from shape + values: rows of [batch_idx, x1, y1, x2, y2, class, score], letterboxed pixels.
    rows_ = raw[raw[:, 6] >= 0.25]
    box = None
    if len(rows_):
        r = rows_[np.argmax(rows_[:, 6])]
        px, py = y["pad"]
        box = [float((r[1] - px) / y["scale"]), float((r[2] - py) / y["scale"]),
               float((r[3] - px) / y["scale"]), float((r[4] - py) / y["scale"])]
    (FIXTURES / "yolo_output.json").write_text(
        json.dumps({"scale": y["scale"], "pad": y["pad"], "box": box}), encoding="utf-8")
    print("fixture box (original px, truth 490,440,790,540):", box)

if __name__ == "__main__":
    main()
