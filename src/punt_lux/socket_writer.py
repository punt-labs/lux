"""Bounded nonblocking socket output; tiny frames do not stall input behind ACKs."""

from __future__ import annotations

from typing import Protocol, Self

from punt_lux.wire_queue import WireQueue


class SendPort(Protocol):
    def send(self, data: memoryview, /) -> int: ...


class SocketWriter:
    _queue: WireQueue

    def __new__(cls, limit: int = 24 * 1024 * 1024) -> Self:
        self = super().__new__(cls)
        self._queue = WireQueue(limit)
        return self

    @property
    def pending_bytes(self) -> int:
        return self._queue.pending

    def append(self, data: bytes) -> None:
        self._queue.append(data)

    def flush(self, target: SendPort) -> None:
        if not self._queue.pending:
            return
        batch = self._queue.batch()
        try:
            sent = target.send(batch)
        except BlockingIOError:
            return
        if sent <= 0 or sent > len(batch):
            raise ConnectionError("invalid socket send count")
        self._queue.advance(sent)

    def clear(self) -> None:
        self._queue.clear()
