"""AES-256-GCM blob encryption. Format: KMT1 | len(key_id) | key_id | nonce(12) | ciphertext+tag."""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"KMT1"
_NONCE = 12


class StorageIntegrityError(Exception):
    """Blob is corrupt, tampered with, moved, or encrypted under another key."""


class Cipher:
    def __init__(self, key: bytes, key_id: str) -> None:
        kid = key_id.encode()
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        if not 1 <= len(kid) <= 255:
            raise ValueError("key_id must be 1-255 bytes")
        self._aead = AESGCM(key)
        self._kid = kid

    def encrypt(self, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(_NONCE)
        return _MAGIC + bytes([len(self._kid)]) + self._kid + nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, blob: bytes, aad: bytes) -> bytes:
        if blob[:4] != _MAGIC or len(blob) < 5:
            raise StorageIntegrityError("bad magic")
        n = blob[4]
        head = 5 + n
        if len(blob) < head + _NONCE + 16:
            raise StorageIntegrityError("truncated blob")
        if blob[5:head] != self._kid:
            raise StorageIntegrityError("unknown key id")
        try:
            return self._aead.decrypt(blob[head : head + _NONCE], blob[head + _NONCE :], aad)
        except InvalidTag as e:
            raise StorageIntegrityError("authentication failed") from e
