"""Blob store interface. The pipeline depends on this, never on a concrete store."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def list_prefix(self, prefix: str) -> list[str]: ...
