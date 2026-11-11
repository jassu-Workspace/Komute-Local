"""Retention sweeper. Reads session files by name only; knows nothing about the engine.

File names below mirror backend.core.audit (storage must not import backend).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from .base import BlobStore
from .crypto import StorageIntegrityError

_STARTED, _RECORD, _MANIFEST = "started.json", "record.json", "manifest.json"
_IMAGE_DIRS = ("originals", "cropped", "compressed")


@dataclass(frozen=True)
class RetentionPolicy:
    rejected_images: timedelta
    approved_originals: timedelta
    incomplete: timedelta = timedelta(hours=1)


@dataclass
class SweepReport:
    deleted_keys: int = 0
    sessions_seen: int = 0


def _session_prefixes(store: BlobStore) -> list[str]:
    seen: set[str] = set()
    for key in store.list_prefix("sessions"):
        parts = key.split("/")
        if len(parts) >= 4:
            seen.add("/".join(parts[:3]))
    return sorted(seen)


def _read_json(store: BlobStore, key: str) -> dict | None:
    try:
        data = json.loads(store.get(key))
    except (KeyError, StorageIntegrityError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def sweep(store: BlobStore, now: datetime, policy: RetentionPolicy) -> SweepReport:
    report = SweepReport()
    for prefix in _session_prefixes(store):
        report.sessions_seen += 1
        manifest = _read_json(store, f"{prefix}/{_MANIFEST}")
        if manifest is None:
            started = _read_json(store, f"{prefix}/{_STARTED}") or {}
            created = _parse_time(started.get("created_at"))
            if created is not None and now - created > policy.incomplete:
                report.deleted_keys += store.delete_prefix(prefix)
            continue
        record = _read_json(store, f"{prefix}/{_RECORD}") or {}
        created = _parse_time(manifest.get("created_at"))
        if created is None:
            continue
        age = now - created
        decision = record.get("decision")
        if decision == "REJECTED" and age > policy.rejected_images:
            for sub in _IMAGE_DIRS:
                report.deleted_keys += store.delete_prefix(f"{prefix}/{sub}")
        elif decision == "APPROVED" and age > policy.approved_originals:
            report.deleted_keys += store.delete_prefix(f"{prefix}/originals")
    return report
