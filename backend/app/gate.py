"""One verification at a time: a memory guard, not a rate limit."""
from __future__ import annotations

import threading


class RunGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()

    def busy(self) -> bool:
        return self._lock.locked()
