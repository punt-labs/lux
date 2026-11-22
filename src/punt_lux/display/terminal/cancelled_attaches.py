"""Attach requests the Display gave up on while their replies were in flight."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Self

from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import Reply, SuccessReply


class CancelledAttaches:
    """Recognize a late reply to a cancelled attach and undo what it opened.

    The daemon may answer an attach after the Display released the replica.
    That reply is expected, not a protocol error; when it succeeded, the
    daemon bound a viewer on a channel nobody will read, so it is closed.
    """

    _send: Callable[[Frame], None]
    _ids: set[int]

    def __new__(cls, send: Callable[[Frame], None]) -> Self:
        self = super().__new__(cls)
        self._send = send
        self._ids = set()
        return self

    def add(self, request_ids: Iterable[int]) -> None:
        self._ids.update(request_ids)

    def consume(self, reply: Reply) -> bool:
        """Consume ``reply`` if it answers a cancelled attach; report whether it did."""
        if reply.request_id not in self._ids:
            return False
        self._ids.discard(reply.request_id)
        if isinstance(reply, SuccessReply):
            channel = reply.result.get("channel")
            if type(channel) is int and channel > 0:
                self._send(Frame(channel, FrameKind.CLOSE, b""))
        return True

    def clear(self) -> None:
        self._ids.clear()
