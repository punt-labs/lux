"""Explicit application lifetime or continuous empty-only headless idle exit."""

from __future__ import annotations

import math
import time
from typing import Self


class DaemonLifetime:
    _timeout: float | None
    _since: float | None

    def __new__(cls, timeout: float | None = 30.0) -> Self:
        # None means a registered application remains available, not a timer.
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("idle timeout must be finite and positive")
        self = super().__new__(cls)
        self._timeout = timeout
        self._since = None
        return self

    def expired(self, clients: int, sessions: int) -> bool:
        if self._timeout is None or clients or sessions:
            self._since = None
            return False
        now = time.monotonic()
        if self._since is None:
            self._since = now
        return now - self._since >= self._timeout
