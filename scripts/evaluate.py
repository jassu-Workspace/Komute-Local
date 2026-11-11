"""Calibration and evaluation harness. Reports hold aggregate numbers only, never personal data.

    python scripts/evaluate.py face     --manifest pairs.csv    --out docs/calibration/face.md
    python scripts/evaluate.py plate    --manifest plates.csv   --out docs/calibration/plate.md
    python scripts/evaluate.py barcode  --manifest cards.csv    --out docs/calibration/barcode.md
    python scripts/evaluate.py liveness --manifest attacks.csv  --out docs/calibration/liveness.md

CSV columns:  face: selfie,licence,same_person,person_id,age_gap_years   plate: image,plate
              barcode: image,province   liveness: image,is_attack
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core  # noqa: E402,F401  (clamps before cv2)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import beta  # noqa: E402


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def required_impostor_trials(target_far: float, confidence: float = 0.95) -> int:
    """Trials with zero false accepts needed to bound the false-accept rate below target_far."""
    return math.ceil(math.log(1 - confidence) / math.log(1 - target_far))


def split_by_person(rows: list[dict], holdout_fraction: float = 0.3) -> tuple[list[dict], list[dict]]:
    tune, hold = [], []
    for r in rows:
        bucket = int(hashlib.sha256(str(r["person_id"]).encode()).hexdigest()[:8], 16) % 1000 / 1000
        (hold if bucket < holdout_fraction else tune).append(r)
    return tune, hold


def pick_threshold(genuine: list[float], impostor: list[float], target_far: float) -> float:
    """Lowest threshold whose false-accept rate on `impostor` is at most target_far."""
    if not impostor:
        raise ValueError("need impostor scores")
    ordered = sorted(impostor, reverse=True)
    allowed = int(math.floor(target_far * len(ordered)))
    return ordered[allowed] + 1e-9 if allowed < len(ordered) else min(ordered)


def _fmt(k: int, n: int) -> str:
    lo, hi = clopper_pearson(k, n)
    return f"{k}/{n} = {100 * k / n:.2f}% (95% CI {100 * lo:.2f}-{100 * hi:.2f}%)" if n else "0/0 (not measured)"


def _rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(out: str, title: str, lines: list[str]) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(f"# {title}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def eval_face(manifest: str, out: str, target_far: float = 1e-4) -> None:
    from backend.core.config import get_settings
    from backend.core.registry import ModelRegistry
    from backend.core.stages.face import FaceDetector, align_112, embed, cosine, pick_licence_face, pick_selfie_face

    s = get_settings()
    reg = ModelRegistry(s.models_dir, s.models_dir / "models.lock", None)
    reg.load()
    det, sess = FaceDetector(reg.face_detector_path), reg.session("face_embedder")

    def vec(path, picker):
        img = cv2.imread(path)
        f = picker(det.detect(img)) if img is not None else None
        return None if f is None or not hasattr(f, "landmarks") else embed(align_112(img, f.landmarks), sess)

    scored = []
    for r in _rows(manifest):
        a, b = vec(r["selfie"], pick_selfie_face), vec(r["licence"], pick_licence_face)
        scored.append({**r, "score": None if a is None or b is None else cosine(a, b)})
    ok = [r for r in scored if r["score"] is not None]
    tune, hold = split_by_person(ok)
    genuine = [r["score"] for r in tune if r["same_person"] == "1"]
    impostor = [r["score"] for r in tune if r["same_person"] == "0"]
    lines = [f"- Pairs: {len(scored)} total, {len(scored) - len(ok)} with no detectable face (excluded)."]
    lines.append(f"- Tuning split: {len(genuine)} genuine, {len(impostor)} impostor. Held-out: {len(hold)} pairs (person-disjoint).")
    if impostor:
        thr = pick_threshold(genuine, impostor, target_far)
        lines.append(f"- Threshold for target false-accept {target_far:.4%} on the tuning split: **{thr:.4f}**.")
        for name, rows_ in (("tuning", tune), ("held-out", hold)):
            g = [r["score"] for r in rows_ if r["same_person"] == "1"]
            i = [r["score"] for r in rows_ if r["same_person"] == "0"]
            lines.append(f"- {name}: false-reject {_fmt(sum(x < thr for x in g), len(g))}; false-accept {_fmt(sum(x >= thr for x in i), len(i))}.")
        for lo, hi in ((0, 9), (10, 19), (20, 200)):
            g = [r["score"] for r in hold if r["same_person"] == "1" and lo <= float(r.get("age_gap_years") or 0) <= hi]
            lines.append(f"- held-out genuine, age gap {lo}-{hi} years: false-reject {_fmt(sum(x < thr for x in g), len(g))}.")
    need = required_impostor_trials(target_far)
    have = sum(1 for r in ok if r["same_person"] == "0")
    lines.append(f"- NOT PROVEN: a false-accept rate of {target_far:.4%} needs at least {need} impostor trials with zero accepts; this set has {have}.")
    _write(out, "Face match calibration", lines)


def eval_plate(manifest: str, out: str) -> None:
    from backend.core.config import get_settings
    from backend.core.registry import ModelRegistry
    from backend.core.stages.vehicle import allowed_indices, crop_with_margin, detect_plate, read_plate
    from backend.core.matching import plates_match, normalise_plate

    s = get_settings()
    reg = ModelRegistry(s.models_dir, s.models_dir / "models.lock", None)
    reg.load()
    allowed = allowed_indices(reg.plate_charset)
    n = found = exact = rule = 0
    for r in _rows(manifest):
        n += 1
        img = cv2.imread(r["image"])
        box = detect_plate(img, reg.session("plate_detector")) if img is not None else None
        if box is None:
            continue
        found += 1
        text, _ = read_plate(crop_with_margin(img, box), reg.session("plate_ocr"), reg.plate_charset, allowed)
        exact += normalise_plate(text) == normalise_plate(r["plate"])
        rule += plates_match(text, r["plate"])
    _write(out, "Plate calibration", [
        f"- Plate found: {_fmt(found, n)}", f"- Exact read: {_fmt(exact, n)}", f"- Pass under the plate rule: {_fmt(rule, n)}",
    ])


def eval_barcode(manifest: str, out: str) -> None:
    from backend.core.aamva import parse_aamva
    from backend.core.policy import IIN_TO_PROVINCE
    from backend.core.stages.barcode import decode_pdf417

    by: Counter = Counter()
    n = decoded = matched = labelled = 0
    for r in _rows(manifest):
        n += 1
        img = cv2.imread(r["image"])
        rec = parse_aamva(decode_pdf417(img)) if img is not None else None
        if rec is None:
            continue
        decoded += 1
        prov = IIN_TO_PROVINCE.get(rec.iin, "UNKNOWN")
        by[prov] += 1
        if r.get("province"):
            labelled += 1
            matched += prov == r["province"]
    lines = [f"- Decoded and parsed: {_fmt(decoded, n)}", "- By issuing province: " + (", ".join(f"{k}={v}" for k, v in sorted(by.items())) or "none")]
    if labelled:
        lines.append(f"- Province matches the label: {_fmt(matched, labelled)}")
    _write(out, "Barcode calibration", lines)


def eval_liveness(manifest: str, out: str) -> None:
    raise SystemExit("liveness evaluation needs the owner's liveness model file (none in the repo yet)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["face", "plate", "barcode", "liveness"])
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    {"face": eval_face, "plate": eval_plate, "barcode": eval_barcode, "liveness": eval_liveness}[a.mode](a.manifest, a.out)


if __name__ == "__main__":
    main()
