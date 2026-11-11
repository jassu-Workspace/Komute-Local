"""Memory and latency benchmark: N sequential verifications on the owner's real licences, in-process.

    python scripts/bench.py --runs 50 --out docs/calibration/bench.md

Writes aggregates only (RSS, latency). Needs KOMUTE_SAMPLES_DIR/raw/p*/ with a licence front and back each.
Dev-only: liveness is skipped (no liveness model yet), so its memory is NOT included.
"""
from __future__ import annotations

import argparse
import base64
import os
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core  # noqa: E402,F401  (clamps before cv2)
import cv2  # noqa: E402
import psutil  # noqa: E402

from backend.core import hardware, policy  # noqa: E402
from backend.core.aamva import parse_aamva  # noqa: E402
from backend.core.config import Settings  # noqa: E402
from backend.core.contracts import Claimed  # noqa: E402
from backend.core.imaging import IMAGE_KEYS  # noqa: E402
from backend.core.pipeline import VerifyInput, build_engine  # noqa: E402
from backend.core.policy import IIN_TO_PROVINCE  # noqa: E402
from backend.core.stages.barcode import decode_pdf417  # noqa: E402


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def load_cards() -> list[dict]:
    root = Path(os.environ["KOMUTE_SAMPLES_DIR"], "raw")
    cards = []
    for person in sorted(root.glob("p*")):
        decoded = [(f, decode_pdf417(cv2.imread(str(f)))) for f in sorted(person.iterdir())]
        back = next(((f, t) for f, t in decoded if t), None)
        front = next((f for f, t in decoded if not t), None)
        if back and front and parse_aamva(back[1]):
            cards.append({"back": back[0].read_bytes(), "front": front.read_bytes(), "rec": parse_aamva(back[1])})
    return cards


class Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak, self._stop_evt, self._p = 0.0, threading.Event(), psutil.Process()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            self.peak = max(self.peak, self._p.memory_info().rss / 1048576)
            time.sleep(0.005)

    def stop(self) -> None:
        self._stop_evt.set()
        self.join()


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--out", default="docs/calibration/bench.md")
    a = ap.parse_args()
    cards = load_cards()
    if not cards:
        raise SystemExit("no readable real licences found")
    vehicle = Path("tests/fixtures/synthetic_vehicle.png").read_bytes()
    tmp = tempfile.mkdtemp(prefix="komute-bench-")
    s = Settings(
        api_key="bench", storage_root=Path(tmp) / "store", storage_key_b64=b64(b"s" * 32), storage_key_id="s1",
        manifest_key_b64=b64(b"m" * 32), manifest_key_id="m1", dev_skip_liveness=True,
    )
    rss_before = hardware.rss_mb()
    engine = build_engine(s)
    rss_loaded = hardware.rss_mb()
    sampler = Sampler()
    sampler.start()
    totals, stage_ms, after, decisions = [], {"barcode": [], "face": [], "vehicle": []}, [], {}
    for i in range(a.runs):
        c = cards[i % len(cards)]
        rec = c["rec"]
        claimed = Claimed(rec.full_name(), rec.date("DBB"), rec.fields["DAQ"], IIN_TO_PROVINCE[rec.iin], "ABC123", "Grey")
        imgs = {"selfie": c["front"], "licence_front": c["front"], "licence_back": c["back"], "vehicle": vehicle}
        inp = VerifyInput(f"bench-{i}", f"d{i % len(cards)}", datetime.now(timezone.utc), "v1", claimed, imgs, f"{i:064d}")
        t = time.perf_counter()
        resp = engine.verify(inp)
        totals.append((time.perf_counter() - t) * 1000)
        decisions[resp["decision"]] = decisions.get(resp["decision"], 0) + 1
        for k in stage_ms:
            stage_ms[k].append(resp["timings_ms"][k])
        after.append(hardware.rss_mb())
    sampler.stop()

    warm = 5
    steady = statistics.median(after[warm:] or after)
    drift = after[-1] - after[min(warm, len(after) - 1)]
    lines = [
        f"- Runs: {a.runs} sequential, cards rotated over {len(cards)} real licences, synthetic vehicle photo. Decisions: {decisions}.",
        f"- Platform: {sys.platform}, Python {sys.version.split()[0]}, threads clamped to 2. Liveness model NOT loaded (none supplied).",
        f"- RSS: process start {rss_before:.0f} MB, after model load {rss_loaded:.0f} MB, steady (median after warm-up) **{steady:.0f} MB**, "
        f"sampled peak **{sampler.peak:.0f} MB**, drift from run {warm} to the last run {drift:+.0f} MB.",
        f"- Latency per verification: p50 {pct(totals, .5):.0f} ms, p95 {pct(totals, .95):.0f} ms, max {max(totals):.0f} ms.",
        "- Stage p50 (ms): " + ", ".join(f"{k} {pct(v, .5):.0f}" for k, v in stage_ms.items()) + ".",
        "- Budget: steady <= 900 MB, peak <= 1200 MB. Result: "
        + ("WITHIN budget" if steady <= 900 and sampler.peak <= 1200 else "OVER budget"),
    ]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("# Memory and latency bench\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
