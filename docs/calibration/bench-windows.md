# Memory and latency bench

- Runs: 50 sequential, cards rotated over 3 real licences, synthetic vehicle photo. Decisions: {'APPROVED': 50}.
- Platform: win32, Python 3.12.13, threads clamped to 2. Liveness model NOT loaded (none supplied).
- RSS: process start 62 MB, after model load 286 MB, steady (median after warm-up) **319 MB**, sampled peak **367 MB**, drift from run 5 to the last run +3 MB.
- Latency per verification: p50 2212 ms, p95 4049 ms, max 4585 ms.
- Stage p50 (ms): barcode 163, face 772, vehicle 130.
- Budget: steady <= 900 MB, peak <= 1200 MB. Result: WITHIN budget
