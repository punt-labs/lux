"""Idle means no clients and no sessions, including retained exited sessions."""

from __future__ import annotations

import math
import time
from typing import Self


class IdleTimer:
    _timeout: float
    _since: float | None

    def __new__(cls, timeout: float = 30.0) -> Self:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("idle timeout must be finite and positive")
        self = super().__new__(cls)
        self._timeout = timeout
        self._since = None
        return self

    def expired(self, clients: int, sessions: int) -> bool:
        if clients or sessions:
            self._since = None
            return False
        now = time.monotonic()
        if self._since is None:
            self._since = now
        return now - self._since >= self._timeout
