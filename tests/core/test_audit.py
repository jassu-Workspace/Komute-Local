import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest

from backend.core.audit import (
    SessionWriter,
    canonical_json,
    is_committed,
    session_prefix,
    verify_session,
)
from storage import Cipher, LocalStore

KEY = b"m" * 32
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path, Cipher(b"s" * 32, "k1"))


def _commit(store, prefix="sessions/d1/r1"):
    w = SessionWriter(store, prefix, KEY, "m1", NOW)
    w.put("originals/selfie.jpg", b"selfie-bytes")
    w.put("cropped/face.webp", b"crop-bytes")
    mid = w.commit({"decision": "APPROVED"})
    return prefix, mid


def test_session_prefix_sanitises():
    assert session_prefix("d/../1", "r 1") == "sessions/d___1/r_1"
    assert ".." not in session_prefix("../..", "../x")


def test_commit_then_verify_ok(store):
    prefix, mid = _commit(store)
    assert is_committed(store, prefix)
    assert len(mid) == 64
    report = verify_session(store, prefix, KEY)
    assert report.ok and report.signature_ok and not report.mismatched and not report.missing


def test_uncommitted_session_not_committed(store):
    w = SessionWriter(store, "sessions/d1/r2", KEY, "m1", NOW)
    w.put("originals/a.jpg", b"x")
    assert not is_committed(store, "sessions/d1/r2")
    assert store.exists("sessions/d1/r2/started.json")


def test_modified_record_reported_mismatched(store):
    prefix, _ = _commit(store)
    store.put(f"{prefix}/record.json", canonical_json({"decision": "REJECTED"}))
    report = verify_session(store, prefix, KEY)
    assert report.signature_ok
    assert report.mismatched == ["record.json"]
    assert not report.ok


def test_modified_manifest_fails_signature(store):
    prefix, _ = _commit(store)
    manifest = json.loads(store.get(f"{prefix}/manifest.json"))
    manifest["files"]["originals/selfie.jpg"] = "0" * 64
    store.put(f"{prefix}/manifest.json", canonical_json(manifest))
    assert not verify_session(store, prefix, KEY).signature_ok


def test_wrong_key_fails_signature(store):
    prefix, _ = _commit(store)
    assert not verify_session(store, prefix, b"w" * 32).signature_ok


def test_modified_file_reported_mismatched(store):
    prefix, _ = _commit(store)
    store.put(f"{prefix}/originals/selfie.jpg", b"tampered")
    report = verify_session(store, prefix, KEY)
    assert report.mismatched == ["originals/selfie.jpg"] and not report.missing


def test_deleted_file_reported_missing_not_mismatched(store):
    prefix, _ = _commit(store)
    store.delete_prefix(f"{prefix}/originals")
    report = verify_session(store, prefix, KEY)
    assert report.missing == ["originals/selfie.jpg"] and not report.mismatched


def test_missing_manifest_is_not_ok(store):
    w = SessionWriter(store, "sessions/d1/r3", KEY, "m1", NOW)
    w.put("a.jpg", b"x")
    assert not verify_session(store, "sessions/d1/r3", KEY).ok


def test_signature_uses_hmac_sha256(store):
    prefix, _ = _commit(store)
    manifest = json.loads(store.get(f"{prefix}/manifest.json"))
    signature = manifest.pop("signature")
    expected = hmac.new(KEY, canonical_json(manifest), hashlib.sha256).hexdigest()
    assert signature == expected


def test_reserved_names_rejected(store):
    w = SessionWriter(store, "sessions/d1/r4", KEY, "m1", NOW)
    for name in ("record.json", "manifest.json", "started.json"):
        with pytest.raises(ValueError):
            w.put(name, b"x")


def test_short_manifest_key_rejected(store):
    with pytest.raises(ValueError):
        SessionWriter(store, "sessions/d1/r5", b"short", "m1", NOW)
