import pytest

from storage import Cipher, StorageIntegrityError

K = bytes(range(32))


def test_roundtrip():
    c = Cipher(K, "k1")
    assert c.decrypt(c.encrypt(b"hello", b"aad"), b"aad") == b"hello"


def test_nonce_is_random():
    c = Cipher(K, "k1")
    assert c.encrypt(b"x", b"a") != c.encrypt(b"x", b"a")


def test_bad_key_or_id_rejected():
    for key, kid in [(b"short", "k"), (K, ""), (K, "k" * 256)]:
        with pytest.raises(ValueError):
            Cipher(key, kid)


def test_wrong_aad_tag_magic_truncation_and_key_id():
    c = Cipher(K, "k1")
    blob = c.encrypt(b"hello", b"aad")
    with pytest.raises(StorageIntegrityError):
        c.decrypt(blob, b"other")
    with pytest.raises(StorageIntegrityError):
        c.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), b"aad")
    with pytest.raises(StorageIntegrityError):
        c.decrypt(b"XXXX" + blob[4:], b"aad")
    with pytest.raises(StorageIntegrityError):
        c.decrypt(blob[:10], b"aad")
    with pytest.raises(StorageIntegrityError):
        c.decrypt(b"", b"aad")
    with pytest.raises(StorageIntegrityError):
        Cipher(K, "k2").decrypt(blob, b"aad")
