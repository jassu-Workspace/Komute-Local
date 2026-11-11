"""Idempotency index: one small encrypted JSON per request_id."""
from __future__ import annotations

import hmac
import json

from storage import BlobStore, StorageIntegrityError, sanitize_folder_name


class IdempotencyConflict(Exception):
    """The request_id was seen before with a different payload."""


def _key(request_id: str) -> str:
    return f"requests/{sanitize_folder_name(request_id)}.json"


def lookup(store: BlobStore, request_id: str, payload_sha256: str) -> dict | None:
    try:
        entry = json.loads(store.get(_key(request_id)))
    except KeyError:
        return None
    except (StorageIntegrityError, ValueError) as e:
        raise IdempotencyConflict("stored idempotency entry is unreadable") from e
    if not hmac.compare_digest(str(entry.get("payload_sha256", "")), payload_sha256):
        raise IdempotencyConflict(request_id)
    return entry["response"]


def save(store: BlobStore, request_id: str, driver_id: str, payload_sha256: str, response: dict) -> None:
    entry = {"driver_id": driver_id, "payload_sha256": payload_sha256, "response": response}
    store.put(_key(request_id), json.dumps(entry, sort_keys=True).encode("utf-8"))
