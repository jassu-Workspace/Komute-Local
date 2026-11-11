"""Encrypted, atomic local-disk blob store."""
from __future__ import annotations

import os
from pathlib import Path

from .crypto import Cipher
from .paths import sanitize_folder_name


class LocalStore:
    def __init__(self, root: Path, cipher: Cipher) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher

    def _path(self, key: str, *, allow_empty: bool = False) -> Path:
        if key == "" and allow_empty:
            return self._root
        segs = key.split("/")
        # sanitize_folder_name maps ".", "..", "unknown" and bad chars away, so equality rejects them
        if any(s == "" or s != sanitize_folder_name(s) for s in segs):
            raise ValueError("invalid storage key")
        p = self._root.joinpath(*segs).resolve()
        if p != self._root and self._root not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(self._cipher.encrypt(data, key.encode()))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            blob = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise KeyError(key) from None
        return self._cipher.decrypt(blob, key.encode())

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def _files(self, base: Path) -> list[Path]:
        if base.is_file():
            return [base]
        if not base.is_dir():
            return []
        return [p for p in base.rglob("*") if p.is_file() and p.suffix != ".tmp"]

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix, allow_empty=True)
        return sorted(p.relative_to(self._root).as_posix() for p in self._files(base))

    def delete_prefix(self, prefix: str) -> int:
        if prefix == "":
            raise ValueError("refusing to delete the whole store")
        base = self._path(prefix)
        files = self._files(base)
        for p in files:
            p.unlink()
        if base.is_dir():
            # deepest first so parents empty out; also sweeps leftover .tmp files' dirs only if empty
            for d in sorted((d for d in base.rglob("*") if d.is_dir()), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass
            try:
                base.rmdir()
            except OSError:
                pass
        return len(files)
