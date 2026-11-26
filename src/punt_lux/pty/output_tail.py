"""Live output not yet sent to a viewer, bounded by a byte limit."""

from __future__ import annotations

from collections import deque
from typing import Self


class OutputTail:
    """Live output not yet sent, bounded by a byte limit."""

    _chunks: deque[bytes]
    _offset: int
    _lag: int
    _limit: int

    def __new__(cls, limit: int) -> Self:
        self = super().__new__(cls)
        self._chunks = deque()
        self._offset = self._lag = 0
        self._limit = limit
        return self

    def __len__(self) -> int:
        return self._lag

    def overflows(self, size: int) -> bool:
        """Whether ``size`` more bytes would pass the limit."""
        return self._lag + size > self._limit

    def push(self, data: bytes) -> None:
        self._chunks.append(data)
        self._lag += len(data)

    def take(self, count: int) -> bytes:
        """Remove and return up to ``count`` bytes from the front."""
        data = self._chunks[0][self._offset : self._offset + count]
        self._offset += len(data)
        self._lag -= len(data)
        if self._offset == len(self._chunks[0]):
            self._chunks.popleft()
            self._offset = 0
        return data

    def clear(self) -> None:
        self._chunks.clear()
        self._offset = self._lag = 0
