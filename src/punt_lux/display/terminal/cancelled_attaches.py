"""Attach requests the Display gave up on while their replies were in flight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Self

from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.replies import Reply, SuccessReply


class CancelledAttaches:
    """Recognize a late reply to a cancelled attach and undo what it opened.

    The daemon may answer an attach after the Display released the replica.
    That reply is expected, not a protocol error; when it succeeded, the
    daemon bound a viewer on a channel nobody will read, so it is closed and
    reported released: the daemon's snapshot and output for it may already be
    in flight behind the reply.

    A name with a cancelled attach still unanswered is *outstanding*: the
    daemon allows one viewer per session on a connection, so a new attach for
    that name would be refused as a duplicate if it arrived first.
    """

    _send: Callable[[Frame], None]
    _released: Callable[[int], None]
    _names: dict[int, str]

    def __new__(
        cls, send: Callable[[Frame], None], released: Callable[[int], None]
    ) -> Self:
        self = super().__new__(cls)
        self._send = send
        self._released = released
        self._names = {}
        return self

    def add(self, requests: Mapping[int, str]) -> None:
        """Cancel ``requests``, each a request id mapped to its session name."""
        self._names.update(requests)

    def outstanding(self, name: str) -> bool:
        return name in self._names.values()

    def consume(self, reply: Reply) -> bool:
        """Consume ``reply`` if it answers a cancelled attach; report whether it did."""
        if self._names.pop(reply.request_id, None) is None:
            return False
        if isinstance(reply, SuccessReply):
            channel = reply.result.get("channel")
            if type(channel) is int and channel > 0:
                self._send(Frame(channel, FrameKind.CLOSE, b""))
                self._released(channel)
        return True

    def clear(self) -> None:
        self._names.clear()
