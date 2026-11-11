from datetime import datetime, timedelta, timezone

import pytest

from backend.core.audit import SessionWriter
from storage import Cipher, LocalStore
from storage.retention import RetentionPolicy, sweep

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
POLICY = RetentionPolicy(rejected_images=timedelta(hours=72), approved_originals=timedelta(days=30))


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path, Cipher(b"s" * 32, "k1"))


def _session(store, name, decision):
    prefix = f"sessions/d1/{name}"
    w = SessionWriter(store, prefix, b"m" * 32, "m1", T0)
    for rel in ("originals/a.jpg", "cropped/f.webp", "compressed/a.webp"):
        w.put(rel, b"img")
    w.commit({"decision": decision})
    return prefix


def _images(store, prefix):
    return {k.split(prefix + "/")[1] for k in store.list_prefix(prefix)}


def test_rejected_images_deleted_after_72h_record_kept(store):
    p = _session(store, "r1", "REJECTED")
    report = sweep(store, T0 + timedelta(hours=73), POLICY)
    assert report.deleted_keys == 3
    assert _images(store, p) == {"manifest.json", "record.json", "started.json"}


def test_rejected_images_kept_at_71h(store):
    p = _session(store, "r2", "REJECTED")
    assert sweep(store, T0 + timedelta(hours=71), POLICY).deleted_keys == 0
    assert len(_images(store, p)) == 6


def test_approved_originals_deleted_after_30d_crops_and_compressed_kept(store):
    p = _session(store, "a1", "APPROVED")
    sweep(store, T0 + timedelta(days=31), POLICY)
    kept = _images(store, p)
    assert "originals/a.jpg" not in kept
    assert {"cropped/f.webp", "compressed/a.webp", "record.json", "manifest.json"} <= kept


def test_approved_untouched_before_30d(store):
    p = _session(store, "a2", "APPROVED")
    assert sweep(store, T0 + timedelta(days=29), POLICY).deleted_keys == 0
    assert "originals/a.jpg" in _images(store, p)


def test_incomplete_session_deleted_after_1h(store):
    prefix = "sessions/d1/inc"
    w = SessionWriter(store, prefix, b"m" * 32, "m1", T0)
    w.put("originals/a.jpg", b"img")
    assert sweep(store, T0 + timedelta(minutes=59), POLICY).deleted_keys == 0
    report = sweep(store, T0 + timedelta(hours=2), POLICY)
    assert report.deleted_keys >= 1
    assert store.list_prefix(prefix) == []


def test_sweep_counts_sessions_and_handles_empty_store(store):
    assert sweep(store, T0, POLICY).sessions_seen == 0
    _session(store, "s1", "REJECTED")
    _session(store, "s2", "APPROVED")
    assert sweep(store, T0, POLICY).sessions_seen == 2
