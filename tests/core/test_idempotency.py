import pytest

from backend.core.idempotency import IdempotencyConflict, lookup, save
from storage import Cipher, LocalStore


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path, Cipher(b"s" * 32, "k1"))


def test_lookup_unknown_returns_none(store):
    assert lookup(store, "r1", "a" * 64) is None


def test_lookup_returns_stored_response(store):
    save(store, "r1", "d1", "a" * 64, {"decision": "APPROVED"})
    assert lookup(store, "r1", "a" * 64) == {"decision": "APPROVED"}


def test_lookup_different_payload_raises_conflict(store):
    save(store, "r1", "d1", "a" * 64, {"decision": "APPROVED"})
    with pytest.raises(IdempotencyConflict):
        lookup(store, "r1", "b" * 64)


def test_corrupt_entry_raises_conflict_not_crash(store, tmp_path):
    save(store, "r1", "d1", "a" * 64, {"decision": "APPROVED"})
    path = next(tmp_path.rglob("r1.json"))
    path.write_bytes(b"garbage")
    with pytest.raises(IdempotencyConflict):
        lookup(store, "r1", "a" * 64)
