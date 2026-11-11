# Memory and latency bench

- Runs: 50 sequential, cards rotated over 3 real licences, synthetic vehicle photo. Decisions: {'APPROVED': 50}.
- Platform: win32, Python 3.12.13, threads clamped to 2. Liveness model NOT loaded (none supplied).
- RSS: process start 63 MB, after model load 300 MB, steady (median after warm-up) **334 MB**, sampled peak **383 MB**, drift from run 5 to the last run -0 MB.
- Latency per verification: p50 1428 ms, p95 1851 ms, max 1965 ms.
- Stage p50 (ms): barcode 96, face 485, vehicle 74.
- Budget: steady <= 900 MB, peak <= 1200 MB. Result: WITHIN budget
