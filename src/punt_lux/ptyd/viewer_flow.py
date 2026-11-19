"""Per-viewer flow: bounded live backlog, credit and ordered snapshot resets."""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.ptyd.credit import CreditWindow
from punt_lux.ptyd.output import SessionSnapshot


class ViewerFlow:
    _channel: int
    _credit: CreditWindow
    _start: bytes | None
    _snapshot: bytes
    _snapshot_offset: int
    _tail: deque[bytes]
    _tail_offset: int
    _lag: int
    _lag_limit: int
    _repaint: bool
    _retry_at: float
    _close: bytes | None
    _close_sent: bool
    _wanted_size: tuple[int, int]
    _actual_size: tuple[int, int]

    def __new__(cls, channel: int, *, lag_limit: int = 4 * 1024 * 1024) -> Self:
        self = super().__new__(cls)
        self._channel = channel
        self._credit = CreditWindow()
        self._start = None
        self._snapshot = b""
        self._snapshot_offset = 0
        self._tail = deque()
        self._tail_offset = self._lag = 0
        self._lag_limit = lag_limit
        self._repaint = False
        self._retry_at = 0.0
        self._close = None
        self._close_sent = False
        self._wanted_size = self._actual_size = (80, 24)
        return self

    @property
    def wanted_size(self) -> tuple[int, int]:
        return self._wanted_size

    def want_size(self, cols: int, rows: int) -> None:
        self._wanted_size = (cols, rows)

    @property
    def actual_size(self) -> tuple[int, int]:
        return self._actual_size

    @property
    def lag_bytes(self) -> int:
        return self._lag

    @property
    def inflight(self) -> int:
        return self._credit.inflight

    @property
    def wants_repaint(self) -> bool:
        return (
            self._repaint
            and self._snapshot_offset == len(self._snapshot)
            and self._credit.available > 0
            and time.monotonic() >= self._retry_at
        )

    def defer_repaint(self) -> None:
        self._retry_at = time.monotonic() + 0.1

    def prepare(
        self,
        checkpoint: SessionSnapshot,
        description: dict[str, object],
        *,
        initial: bool = False,
    ) -> None:
        """Drop only unsent backlog; old in-flight bytes retain their credit debt."""
        self._actual_size = (checkpoint.cols, checkpoint.rows)
        metadata = checkpoint.to_dict()
        metadata.update(
            channel=self._channel,
            ended=description["ended"],
            exit_code=description["exit_code"],
        )
        self._start = None if initial else json.dumps(metadata).encode()
        self._snapshot, self._snapshot_offset = checkpoint.data, 0
        self._tail.clear()
        self._tail_offset = self._lag = 0
        self._repaint = False
        if description["ended"]:
            self.finish("exited", description["exit_code"])

    def append(self, data: bytes) -> None:
        if self._repaint or self._close_sent:
            return
        if self._lag + len(data) > self._lag_limit:
            self._tail.clear()
            self._tail_offset = self._lag = 0
            self._repaint = True
        elif data:
            self._tail.append(data)
            self._lag += len(data)

    def acknowledge(self, amount: int) -> None:
        self._credit.acknowledge(amount)

    def finish(self, reason: str, exit_code: object = None) -> None:
        if reason != "exited":
            self._start = None
            self._snapshot = b""
            self._snapshot_offset = 0
            self._tail.clear()
            self._tail_offset = self._lag = 0
            self._repaint = False
        self._close = json.dumps({"reason": reason, "exit_code": exit_code}).encode()

    def drain(self) -> list[Frame]:
        frames: list[Frame] = []
        if self._start is not None:
            frames.append(Frame(self._channel, FrameKind.SNAPSHOT_START, self._start))
            self._start = None
        for _ in range(4):
            payload = self._payload()
            if payload is None:
                break
            kind, data = payload
            self._credit.send(len(data))
            frames.append(Frame(self._channel, kind, data))
        if self._done() and self._close is not None and not self._close_sent:
            frames.append(Frame(self._channel, FrameKind.CLOSE, self._close))
            self._close_sent = True
        return frames

    def _payload(self) -> tuple[FrameKind, bytes] | None:
        count = min(64 * 1024, self._credit.available)
        if count == 0:
            return None
        if self._snapshot_offset < len(self._snapshot):
            data = self._snapshot[self._snapshot_offset : self._snapshot_offset + count]
            self._snapshot_offset += len(data)
            if self._snapshot_offset == len(self._snapshot):
                self._snapshot = b""
                self._snapshot_offset = 0
            return FrameKind.SNAPSHOT, data
        if self._repaint or not self._tail:
            return None
        data = self._tail[0][self._tail_offset : self._tail_offset + count]
        self._tail_offset += len(data)
        self._lag -= len(data)
        if self._tail_offset == len(self._tail[0]):
            self._tail.popleft()
            self._tail_offset = 0
        return FrameKind.DATA, data

    def _done(self) -> bool:
        return (
            self._snapshot_offset == len(self._snapshot)
            and not self._tail
            and not self._repaint
        )
