from backend.core.monitor import EngineMonitor, SystemSampler


def test_engine_monitor_tracks_stage_counts_and_steps():
    m = EngineMonitor()
    m.begin()
    m.stage("face")
    snap = m.snapshot()
    assert snap["busy"] and snap["stage"] == "face" and snap["stage_for_ms"] >= 0
    m.done({"decision": "APPROVED", "reasons": [], "timings_ms": {"total": 900.0, "face": 500.0},
            "memory_trace": {"start_mb": 300, "peak_mb": 380, "end_mb": 310}}, {"face.detect": 40.0})
    m.begin()
    m.done({"decision": "REJECTED", "reasons": [{"code": "NAME_MISMATCH"}], "timings_ms": {"total": 100.0}}, {"face.detect": 60.0})
    m.begin()
    m.failed()
    snap = m.snapshot()
    assert not snap["busy"] and snap["stage"] is None
    assert snap["counts"] == {"verifications": 2, "approved": 1, "rejected": 1, "errors": 1}
    assert snap["steps"]["face.detect"] == {"count": 2, "last_ms": 60.0, "mean_ms": 50.0, "min_ms": 40.0, "max_ms": 60.0}
    assert snap["last"]["reasons"] == ["NAME_MISMATCH"]


def test_abandon_goes_idle_without_counting():
    m = EngineMonitor()
    m.begin()
    m.abandon()
    assert m.snapshot()["counts"]["verifications"] == 0 and not m.snapshot()["busy"]


def test_system_sampler_records_and_bounds_history(tmp_path):
    s = SystemSampler(tmp_path, interval_s=0.01, history=5)
    for _ in range(8):
        s._take()
    latest = s.latest()
    assert latest["memory"]["process_rss_mb"] > 0 and latest["disk"]["total_gb"] > 0
    assert len(latest["cpu"]["per_core_percent"]) == s.static["cpu_logical_cores"]
    assert len(s.history()) == 5 and len(s.history()[0]) == 5


def test_skipped_stage_is_not_counted_as_a_run():
    m = EngineMonitor()
    m.begin()
    m.done({"decision": "REJECTED", "stages": {"barcode": {"ran": True}, "face": {"ran": False}},
            "timings_ms": {"total": 50.0, "barcode": 40.0, "face": 0.0}}, {})
    steps = m.snapshot()["steps"]
    assert "stage.face" not in steps and steps["stage.barcode"]["count"] == 1
