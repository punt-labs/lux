"""Bounded, ordered input across partial writes to a nonblocking PTY."""

from __future__ import annotations

import os
from typing import Self


class InputBuffer:
    """Retain unwritten bytes; backpressure must never silently drop a paste."""

    _pending: bytearray
    _limit: int

    def __new__(cls, limit: int = 1024 * 1024) -> Self:
        if limit <= 0:
            raise ValueError("input limit must be positive")
        self = super().__new__(cls)
        self._pending = bytearray()
        self._limit = limit
        return self

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    def append(self, data: bytes) -> None:
        """Reject overflow before changing the existing queue."""
        if len(self._pending) + len(data) > self._limit:
            raise BufferError("terminal input queue is full")
        self._pending.extend(data)

    def flush(self, fd: int) -> None:
        """Attempt one write; leave a short write or EAGAIN tail for next pump."""
        if not self._pending:
            return
        try:
            written = os.write(fd, self._pending)
        except BlockingIOError:
            return
        del self._pending[:written]

    def clear(self) -> None:
        self._pending.clear()
