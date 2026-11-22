"""Bounded ordered byte queue with a bounded scatter-to-contiguous send batch."""

from __future__ import annotations

from collections import deque
from typing import Self


class WireQueue:
    _chunks: deque[bytes]
    _offset: int
    _pending: int
    _limit: int

    def __new__(cls, limit: int) -> Self:
        self = super().__new__(cls)
        self._chunks = deque()
        self._offset = self._pending = 0
        self._limit = limit
        return self

    @property
    def pending(self) -> int:
        return self._pending

    def append(self, data: bytes) -> None:
        if self._pending + len(data) > self._limit:
            raise BufferError("viewer output queue is full")
        if data:
            self._chunks.append(data)
            self._pending += len(data)

    def batch(self) -> memoryview:
        """Join tiny frames; keep the large single-chunk path zero-copy."""
        first = memoryview(self._chunks[0])[self._offset : self._offset + 64 * 1024]
        if len(first) == 64 * 1024 or len(self._chunks) == 1:
            return first
        data = bytearray(first)
        chunks = iter(self._chunks)
        next(chunks)
        for chunk in chunks:
            remaining = 64 * 1024 - len(data)
            if not remaining:
                break
            data.extend(memoryview(chunk)[:remaining])
        return memoryview(data)

    def advance(self, count: int) -> None:
        self._pending -= count
        while count:
            remaining = len(self._chunks[0]) - self._offset
            taken = min(count, remaining)
            self._offset += taken
            count -= taken
            if self._offset == len(self._chunks[0]):
                self._chunks.popleft()
                self._offset = 0

    def clear(self) -> None:
        self._chunks.clear()
        self._offset = self._pending = 0
