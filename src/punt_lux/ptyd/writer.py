"""Bounded nonblocking wire output, retaining short-send tails in order."""

from __future__ import annotations

from collections import deque
from typing import Protocol, Self


class SendPort(Protocol):
    def send(self, data: memoryview, /) -> int: ...


class WireWriter:
    """One connection's queue; a slow viewer cannot block the daemon."""

    _chunks: deque[bytes]
    _offset: int
    _pending: int
    _limit: int

    def __new__(cls, limit: int = 24 * 1024 * 1024) -> Self:
        self = super().__new__(cls)
        self._chunks = deque()
        self._offset = 0
        self._pending = 0
        self._limit = limit
        return self

    @property
    def pending_bytes(self) -> int:
        return self._pending

    def append(self, data: bytes) -> None:
        if self._pending + len(data) > self._limit:
            raise BufferError("viewer output queue is full")
        if data:
            self._chunks.append(data)
            self._pending += len(data)

    def flush(self, target: SendPort) -> None:
        if not self._chunks:
            return
        head = self._chunks[0]
        try:
            sent = target.send(
                memoryview(head)[self._offset : self._offset + 64 * 1024]
            )
        except BlockingIOError:
            return
        if sent <= 0:
            raise ConnectionError("viewer stopped accepting output")
        self._offset += sent
        self._pending -= sent
        if self._offset == len(head):
            self._chunks.popleft()
            self._offset = 0

    def clear(self) -> None:
        self._chunks.clear()
        self._offset = self._pending = 0
