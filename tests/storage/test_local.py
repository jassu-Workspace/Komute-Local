import os

import pytest

from storage import Cipher, LocalStore, StorageIntegrityError

K = bytes(range(32))


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path / "root", Cipher(K, "k1"))


def test_roundtrip(store):
    store.put("s1/originals/selfie.jpg", b"data")
    assert store.get("s1/originals/selfie.jpg") == b"data"
    assert store.exists("s1/originals/selfie.jpg")
    assert not store.exists("s1/nope")
    with pytest.raises(KeyError):
        store.get("s1/nope")


def test_overwrite(store):
    store.put("a/b", b"1")
    store.put("a/b", b"2")
    assert store.get("a/b") == b"2"


def test_tamper_detected(store):
    store.put("a/b", b"data")
    f = store._root / "a" / "b"
    raw = bytearray(f.read_bytes())
    raw[-1] ^= 1
    f.write_bytes(bytes(raw))
    with pytest.raises(StorageIntegrityError):
        store.get("a/b")


def test_file_swap_detected(store):
    store.put("a/one", b"AAA")
    store.put("a/two", b"BBB")
    (store._root / "a" / "two").write_bytes((store._root / "a" / "one").read_bytes())
    with pytest.raises(StorageIntegrityError):
        store.get("a/two")


@pytest.mark.parametrize(
    "key",
    ["../x", "a/../../b", "C:\\x", "a//b", "", "/abs", "a/", "a\\b", "C:", ".", "a/./b", "a b"],
)
def test_rejects_traversal_keys(store, key):
    with pytest.raises(ValueError):
        store.put(key, b"x")
    with pytest.raises(ValueError):
        store.get(key)
    with pytest.raises(ValueError):
        store.exists(key)


def test_plaintext_never_on_disk(store):
    store.put("a/name", b"SECRET-NAME")
    for dirpath, _, files in os.walk(store._root):
        for n in files:
            assert b"SECRET-NAME" not in open(os.path.join(dirpath, n), "rb").read()


def test_delete_prefix_counts(store):
    store.put("s1/a", b"1")
    store.put("s1/sub/b", b"2")
    store.put("s2/c", b"3")
    assert store.delete_prefix("s1") == 2
    assert not store.exists("s1/a")
    assert not (store._root / "s1").exists()
    assert store.exists("s2/c")
    assert store.delete_prefix("missing") == 0
    with pytest.raises(ValueError):
        store.delete_prefix("")


def test_delete_prefix_is_segment_aligned(store):
    store.put("s1/a", b"1")
    store.put("s10/a", b"2")
    assert store.delete_prefix("s1") == 1
    assert store.exists("s10/a")


def test_list_prefix_sorted_forward_slashes(store):
    store.put("s1/b", b"1")
    store.put("s1/sub/a", b"2")
    store.put("s2/c", b"3")
    assert store.list_prefix("s1") == ["s1/b", "s1/sub/a"]
    assert store.list_prefix("") == ["s1/b", "s1/sub/a", "s2/c"]
    assert store.list_prefix("nope") == []


def test_tmp_file_left_by_crash_is_ignored_by_list(store):
    store.put("s1/a", b"1")
    (store._root / "s1" / "b.tmp").write_bytes(b"partial")
    assert store.list_prefix("s1") == ["s1/a"]


def test_failed_write_leaves_no_tmp(store, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr("storage.local.os.replace", boom)
    with pytest.raises(OSError):
        store.put("s1/a", b"1")
    assert list(store._root.rglob("*.tmp")) == []
