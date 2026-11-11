"""Stage 3: plate detection, masked OCR, plate rule, colour."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

PLATE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
YOLO_SIZE = 384
OCR_HEIGHT = 48
OCR_MAX_WIDTH = 320
OCR_MIN_WIDTH = 48
PLATE_MARGIN = 0.08


@dataclass(frozen=True)
class PlateBox:
    x1: int
    y1: int
    x2: int
    y2: int
    score: float

    @property
    def w(self) -> int:
        return self.x2 - self.x1

    @property
    def h(self) -> int:
        return self.y2 - self.y1


def letterbox(img_bgr: np.ndarray, size: int = YOLO_SIZE) -> tuple[np.ndarray, float, tuple[int, int]]:
    h, w = img_bgr.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    pad = ((size - nw) // 2, (size - nh) // 2)
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[pad[1] : pad[1] + nh, pad[0] : pad[0] + nw] = resized
    tensor = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    return tensor, scale, pad


def decode_end2end(
    output: np.ndarray, scale: float, pad: tuple[int, int], min_score: float = 0.35
) -> list[PlateBox]:
    """Output rows are [batch, x1, y1, x2, y2, class, score] in letterboxed pixels (NMS is in the graph)."""
    rows = np.asarray(output).reshape(-1, 7)
    boxes = []
    for r in rows:
        if r[6] < min_score:
            continue
        x1, x2 = (r[1] - pad[0]) / scale, (r[3] - pad[0]) / scale
        y1, y2 = (r[2] - pad[1]) / scale, (r[4] - pad[1]) / scale
        boxes.append(PlateBox(int(x1), int(y1), int(x2), int(y2), float(r[6])))
    return boxes


def detect_plate(img_bgr: np.ndarray, session, min_score: float = 0.35) -> Optional[PlateBox]:
    tensor, scale, pad = letterbox(img_bgr)
    out = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    h, w = img_bgr.shape[:2]
    best = None
    for b in decode_end2end(out, scale, pad, min_score):
        clipped = PlateBox(max(0, b.x1), max(0, b.y1), min(w, b.x2), min(h, b.y2), b.score)
        if clipped.w >= 4 and clipped.h >= 4 and (best is None or clipped.score > best.score):
            best = clipped
    return best


def crop_with_margin(img_bgr: np.ndarray, box: PlateBox, margin: float = PLATE_MARGIN) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    mx, my = int(box.w * margin), int(box.h * margin)
    return img_bgr[max(0, box.y1 - my) : min(h, box.y2 + my), max(0, box.x1 - mx) : min(w, box.x2 + mx)]


def allowed_indices(charset: list[str]) -> np.ndarray:
    """Class indices the plate may use: the CTC blank (0) plus the A-Z and 0-9 classes."""
    return np.array([0] + [i for i, c in enumerate(charset) if c in PLATE_CHARS], dtype=np.int64)


def ctc_decode(probs: np.ndarray, charset: list[str], allowed: np.ndarray) -> tuple[str, float]:
    """Greedy CTC over [T, C]. The model's own argmax decides blank-or-character; a character step takes
    the best allowed plate character, so CJK or symbol classes can never reach the output."""
    space = len(charset) - 1
    chars_only = allowed[allowed != 0]
    best_full = probs.argmax(axis=1)
    best_plate = chars_only[probs[:, chars_only].argmax(axis=1)]
    out: list[str] = []
    confs: list[float] = []
    prev = -1
    for t in range(probs.shape[0]):
        c = int(best_full[t])
        if c == 0 or c == space:
            prev = -1 if c == 0 else prev
            continue
        k = int(best_plate[t])
        if k != prev:
            out.append(charset[k])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(out), (float(np.mean(confs)) if confs else 0.0)


def read_plate(crop_bgr: np.ndarray, session, charset: list[str], allowed: np.ndarray) -> tuple[str, float]:
    if crop_bgr is None or crop_bgr.size == 0:
        return "", 0.0
    h, w = crop_bgr.shape[:2]
    width = int(min(OCR_MAX_WIDTH, max(OCR_MIN_WIDTH, round(w * OCR_HEIGHT / h))))
    resized = cv2.resize(crop_bgr, (width, OCR_HEIGHT), interpolation=cv2.INTER_LINEAR)
    blob = ((resized.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    out = np.asarray(session.run(None, {session.get_inputs()[0].name: blob})[0])
    return ctc_decode(out[0], charset, allowed)


# ---- colour (advisory) ----
PALETTE = [
    ("Black", "#111111", (12.0, 0.0, 0.0)),
    ("Dark Charcoal / Graphite", "#2e2e33", (24.0, -0.5, -2.0)),
    ("Grey", "#6b6f76", (48.0, -0.5, -2.0)),
    ("Silver / Metallic", "#c0c4c8", (78.0, -0.8, -1.5)),
    ("White", "#f5f6f8", (96.0, -0.5, -0.5)),
    ("Deep Navy Blue", "#122036", (16.0, 4.0, -22.0)),
    ("Blue", "#1d589e", (38.0, 8.0, -42.0)),
    ("Light Blue", "#6da6db", (68.0, -6.0, -30.0)),
    ("Red", "#b31b1b", (38.0, 60.0, 38.0)),
    ("Maroon / Burgundy", "#4a121a", (20.0, 32.0, 12.0)),
    ("Green", "#1b5e20", (35.0, -38.0, 26.0)),
    ("Yellow / Gold", "#fbc02d", (78.0, 4.0, 75.0)),
    ("Orange", "#e65100", (52.0, 52.0, 60.0)),
    ("Brown", "#4e342e", (28.0, 12.0, 12.0)),
]
_PALETTE_LAB = np.array([p[2] for p in PALETTE], dtype=np.float32)

COLOUR_FAMILIES: dict[str, set[str]] = {
    "black": {"Black"},
    "grey": {"Grey", "Dark Charcoal / Graphite"},
    "gray": {"Grey", "Dark Charcoal / Graphite"},
    "charcoal": {"Dark Charcoal / Graphite", "Grey"},
    "graphite": {"Dark Charcoal / Graphite", "Grey"},
    "silver": {"Silver / Metallic", "Grey"},
    "white": {"White"},
    "blue": {"Blue", "Light Blue", "Deep Navy Blue"},
    "navy": {"Deep Navy Blue"},
    "red": {"Red", "Maroon / Burgundy"},
    "maroon": {"Maroon / Burgundy"},
    "burgundy": {"Maroon / Burgundy"},
    "green": {"Green"},
    "yellow": {"Yellow / Gold"},
    "gold": {"Yellow / Gold"},
    "orange": {"Orange"},
    "brown": {"Brown"},
}
# The spec filters L* > 92 as glare, but its own White reference is L* 96, so white cars would vanish.
GLARE_L, SHADOW_L = 99.0, 5.0
MIN_COLOUR_PIXELS = 200
MAX_KMEANS_PIXELS = 20_000


@dataclass(frozen=True)
class ColourResult:
    name: str
    hex: str
    delta_e: float


def _patches(img: np.ndarray, b: PlateBox) -> list[np.ndarray]:
    h, w = img.shape[:2]
    pw, ph = b.w, b.h
    boxes = [
        (b.x1, b.y1 - 0.40 * ph, pw, 0.35 * ph),
        (b.x1, b.y2 + 0.05 * ph, pw, 0.35 * ph),
        (b.x1 - 0.35 * pw, b.y1, 0.30 * pw, ph),
        (b.x2 + 0.05 * pw, b.y1, 0.30 * pw, ph),
    ]
    out = []
    for x, y, bw, bh in boxes:
        x0, y0, x1, y1 = max(0, int(x)), max(0, int(y)), min(w, int(x + bw)), min(h, int(y + bh))
        if x1 > x0 and y1 > y0:
            out.append(img[y0:y1, x0:x1].reshape(-1, 3))
    return out


def classify_colour(img_bgr: np.ndarray, plate: PlateBox) -> Optional[ColourResult]:
    parts = _patches(img_bgr, plate)
    if not parts:
        return None
    pixels = np.concatenate(parts).astype(np.float32) / 255.0
    lab = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2Lab).reshape(-1, 3)
    lab = lab[(lab[:, 0] > SHADOW_L) & (lab[:, 0] < GLARE_L)]
    if len(lab) < MIN_COLOUR_PIXELS:
        return None
    if len(lab) > MAX_KMEANS_PIXELS:
        lab = lab[np.random.default_rng(0).choice(len(lab), MAX_KMEANS_PIXELS, replace=False)]
    cv2.setRNGSeed(0)
    k = min(3, len(lab))
    _, labels, centres = cv2.kmeans(
        np.ascontiguousarray(lab), k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 3,
        cv2.KMEANS_PP_CENTERS,
    )
    dominant = centres[np.bincount(labels.ravel()).argmax()]
    dist = np.linalg.norm(_PALETTE_LAB - dominant, axis=1)
    i = int(dist.argmin())
    return ColourResult(PALETTE[i][0], PALETTE[i][1], round(float(dist[i]), 2))


def claimed_colour_family(claimed: str) -> Optional[set[str]]:
    words = claimed.lower().replace("-", " ").replace("/", " ").split()
    family: set[str] = set()
    for w in words:
        family |= COLOUR_FAMILIES.get(w, set())
    if "light" in words and "blue" in words:
        family = {"Light Blue"}
    return family or None


# ---- Stage 3 assembly ----
import time  # noqa: E402
from typing import Any, Callable  # noqa: E402

from ..contracts import Advisory, Claimed, Reason, ReasonCode, StageResult  # noqa: E402
from ..matching import plates_match  # noqa: E402


def run_vehicle_stage(
    vehicle_img: np.ndarray,
    claimed: Claimed,
    detect: Callable[[np.ndarray], Optional[PlateBox]],
    read: Callable[[np.ndarray], tuple[str, float]],
    settings: Any,
) -> StageResult:
    result = StageResult(name="vehicle", ran=True)
    t0 = time.perf_counter()
    box = detect(vehicle_img)
    result.timings_ms["detect"] = round((time.perf_counter() - t0) * 1000, 1)
    if box is None:
        result.reasons.append(Reason.of(ReasonCode.PLATE_NOT_FOUND))
        result.details = {"plate_found": False}
        return result

    crop = crop_with_margin(vehicle_img, box)
    t1 = time.perf_counter()
    text, conf = read(crop)
    result.timings_ms["ocr"] = round((time.perf_counter() - t1) * 1000, 1)
    result.crops = {"plate": crop}
    result.details = {"plate_found": True, "plate_read": text, "plate_confidence": round(conf, 3), "plate_matched": False}
    if not text or conf < settings.plate_min_confidence:
        result.reasons.append(Reason.of(ReasonCode.PLATE_UNREADABLE))
    elif plates_match(text, claimed.plate_number):
        result.details["plate_matched"] = True
    else:
        result.reasons.append(Reason.of(ReasonCode.PLATE_MISMATCH))

    t2 = time.perf_counter()
    colour = classify_colour(vehicle_img, box)
    result.timings_ms["colour"] = round((time.perf_counter() - t2) * 1000, 1)
    family = claimed_colour_family(claimed.vehicle_colour)
    if colour is None or family is None:
        result.advisories.append(Advisory.COLOUR_UNVERIFIED)
    else:
        result.details.update(colour=colour.name, colour_hex=colour.hex, delta_e=colour.delta_e)
        if colour.name not in family:
            result.advisories.append(Advisory.COLOUR_MISMATCH)
    return result
