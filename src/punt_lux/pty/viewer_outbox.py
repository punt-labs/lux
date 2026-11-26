"""What is queued for one viewer: the snapshot, live output and the close notice."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.close_notice import CloseNotice
from punt_lux.pty.output_tail import OutputTail
from punt_lux.pty.snapshot_outbox import SnapshotOutbox
from punt_lux.wire.stream.frames import Frame, FrameKind

if TYPE_CHECKING:
    from punt_lux.pty.credit import CreditWindow

MAX_PAYLOAD = 64 * 1024
LAG_LIMIT = 4 * 1024 * 1024
FRAMES_PER_DRAIN = 4


class ViewerOutbox:
    """Order and frame a viewer's queued bytes under its credit window."""

    _channel: int
    _start: bytes
    _snapshot: SnapshotOutbox
    _tail: OutputTail
    _close: CloseNotice

    def __new__(cls, channel: int) -> Self:
        self = super().__new__(cls)
        self._channel = channel
        self._start = b""
        self._snapshot = SnapshotOutbox()
        self._tail = OutputTail(LAG_LIMIT)
        self._close = CloseNotice()
        return self

    @property
    def lag_bytes(self) -> int:
        return len(self._tail)

    @property
    def snapshot_sent(self) -> bool:
        return not self._snapshot

    @property
    def close_sent(self) -> bool:
        return self._close.sent

    def begin(self, snapshot: bytes, start: bytes) -> None:
        """Queue ``snapshot``, dropping unsent output.

        ``start`` is the metadata for a SNAPSHOT_START frame; empty when the
        attach reply already carried it.
        """
        self._start = start
        self._snapshot.load(snapshot)
        self._tail.clear()

    def abandon(self) -> None:
        """Drop everything unsent; the close notice stays."""
        self.begin(b"", b"")

    def drop_tail(self) -> None:
        self._tail.clear()

    def overflows(self, size: int) -> bool:
        return self._tail.overflows(size)

    def push(self, data: bytes) -> None:
        self._tail.push(data)

    def finish(self, reason: str, exit_code: object) -> None:
        self._close.set(reason, exit_code)

    def drain(self, credit: CreditWindow, *, resyncing: bool) -> list[Frame]:
        """Frame what the credit window allows; CLOSE follows the last byte."""
        frames: list[Frame] = []
        if self._start:
            frames.append(Frame(self._channel, FrameKind.SNAPSHOT_START, self._start))
            self._start = b""
        for _ in range(FRAMES_PER_DRAIN):
            payload = self._payload(credit, resyncing=resyncing)
            if payload is None:
                break
            kind, data = payload
            credit.send(len(data))
            frames.append(Frame(self._channel, kind, data))
        if not (self._snapshot or self._tail or resyncing):
            frames.extend(self._close.take(self._channel))
        return frames

    def _payload(
        self, credit: CreditWindow, *, resyncing: bool
    ) -> tuple[FrameKind, bytes] | None:
        count = min(MAX_PAYLOAD, credit.available)
        if count == 0:
            return None
        if self._snapshot:
            return FrameKind.SNAPSHOT, self._snapshot.take(count)
        if resyncing or not self._tail:
            return None
        return FrameKind.DATA, self._tail.take(count)
