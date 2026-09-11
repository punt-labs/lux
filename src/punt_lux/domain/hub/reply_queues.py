"""ReplyQueues -- the typed Ack/Pong/QueryResponse routing for one connection.

Extracted from :class:`DisplayLink` (PY-OO-5, PY-IC-6): ack, pong, and
query-response routing is one cohesive concern -- the background listener
puts a typed reply in, and :meth:`DisplayLink.show`, :meth:`DisplayLink.ping`,
and :meth:`DisplayLink.query` block on getting one out -- so it owns its
three queues as a single value the transport calls into, rather than three
loose ``queue.SimpleQueue`` fields the transport reaches into directly.
"""

from __future__ import annotations

import queue
from typing import Any, Self, cast, final

from punt_lux.protocol import AckMessage, Message, PongMessage, QueryResponse

__all__ = ["ReplyQueues"]


def _drain(q: queue.SimpleQueue[Any]) -> None:
    """Discard all items from a :class:`queue.SimpleQueue`."""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break


@final
class ReplyQueues:
    """Typed Ack/Pong/QueryResponse queues the listener fills and callers drain."""

    _ack: queue.SimpleQueue[AckMessage]
    _pong: queue.SimpleQueue[PongMessage]
    _query: queue.SimpleQueue[QueryResponse]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._ack = queue.SimpleQueue()
        self._pong = queue.SimpleQueue()
        self._query = queue.SimpleQueue()
        return self

    def put(self, msg: AckMessage | PongMessage | QueryResponse) -> None:
        """Route a reply to its typed queue."""
        if isinstance(msg, AckMessage):
            self._ack.put(msg)
        elif isinstance(msg, PongMessage):
            self._pong.put(msg)
        else:
            self._query.put(msg)

    def get_ack(self, timeout: float) -> AckMessage | None:
        """Block up to ``timeout`` for the next :class:`AckMessage`."""
        try:
            return self._ack.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_typed[T: Message](self, expected: type[T], timeout: float) -> T | None:
        """Block up to ``timeout`` for the next reply of ``expected`` type."""
        by_type: dict[type[Message], queue.SimpleQueue[Any]] = {
            PongMessage: self._pong,
            QueryResponse: self._query,
        }
        queued = by_type[cast("type[Message]", expected)]
        try:
            return cast("T", queued.get(timeout=timeout))
        except queue.Empty:
            return None

    def drain(self) -> None:
        """Discard every queued reply -- stragglers from a dying listener."""
        _drain(self._ack)
        _drain(self._pong)
        _drain(self._query)
