"""Session audit: write files through a BlobStore, then seal them with a signed manifest.

`manifest.json` is written last. A session without it is incomplete and ignored by readers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from storage import BlobStore, StorageIntegrityError, sanitize_folder_name

STARTED = "started.json"
RECORD = "record.json"
MANIFEST = "manifest.json"


def session_prefix(driver_id: str, request_id: str) -> str:
    return f"sessions/{sanitize_folder_name(driver_id)}/{sanitize_folder_name(request_id)}"


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sign(manifest_without_signature: dict, key: bytes) -> str:
    return hmac.new(key, canonical_json(manifest_without_signature), hashlib.sha256).hexdigest()


class SessionWriter:
    def __init__(
        self, store: BlobStore, prefix: str, manifest_key: bytes, manifest_key_id: str, now: datetime
    ) -> None:
        if len(manifest_key) < 32:
            raise ValueError("manifest key must be at least 32 bytes")
        self._store = store
        self._prefix = prefix
        self._key = manifest_key
        self._key_id = manifest_key_id
        self._now = now
        self._files: dict[str, str] = {}
        store.put(f"{prefix}/{STARTED}", canonical_json({"created_at": now.isoformat()}))

    def put(self, rel_path: str, data: bytes) -> None:
        if rel_path in (STARTED, RECORD, MANIFEST):
            raise ValueError(f"reserved name: {rel_path}")
        self._store.put(f"{self._prefix}/{rel_path}", data)
        self._files[rel_path] = _sha256(data)

    def commit(self, record: dict) -> str:
        record_bytes = canonical_json(record)
        self._store.put(f"{self._prefix}/{RECORD}", record_bytes)
        manifest = {
            "files": dict(sorted(self._files.items())),
            "record_sha256": _sha256(record_bytes),
            "key_id": self._key_id,
            "created_at": self._now.isoformat(),
        }
        manifest["signature"] = _sign(manifest, self._key)
        manifest_bytes = canonical_json(manifest)
        self._store.put(f"{self._prefix}/{MANIFEST}", manifest_bytes)
        return _sha256(manifest_bytes)


@dataclass
class VerifyReport:
    signature_ok: bool
    mismatched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.signature_ok and not self.mismatched and not self.missing


def is_committed(store: BlobStore, prefix: str) -> bool:
    return store.exists(f"{prefix}/{MANIFEST}")


def verify_session(store: BlobStore, prefix: str, manifest_key: bytes) -> VerifyReport:
    try:
        manifest = json.loads(store.get(f"{prefix}/{MANIFEST}"))
    except (KeyError, StorageIntegrityError, ValueError):
        return VerifyReport(signature_ok=False, missing=[MANIFEST])
    signature = manifest.pop("signature", "")
    report = VerifyReport(signature_ok=hmac.compare_digest(signature, _sign(manifest, manifest_key)))
    expected = dict(manifest.get("files", {}))
    expected[RECORD] = manifest.get("record_sha256", "")
    for rel, sha in sorted(expected.items()):
        key = f"{prefix}/{rel}"
        if not store.exists(key):
            report.missing.append(rel)
            continue
        try:
            actual = _sha256(store.get(key))
        except StorageIntegrityError:
            report.mismatched.append(rel)
            continue
        if not hmac.compare_digest(actual, sha):
            report.mismatched.append(rel)
    return report
