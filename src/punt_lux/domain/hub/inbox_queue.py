"""The bounded per-connection inbox a subscriber's ``recv`` leg drains.

A :class:`BoundedInbox` is one MCP session's FIFO of undelivered
``ObserverMessage`` fan-outs. When a full inbox admits a new message the oldest
undelivered one is dropped and the loss is logged -- the same backstop the
callback hold applies (``_HOLD_CAPACITY`` in ``callback_hold``): it guards an
inbox whose ``recv`` leg has stopped draining -- a departed or wedged
subscriber -- from growing without bound, and it is not a delivery quota.

The primitive is deliberately its own module, separate from the connection
registry and Hub-writer wiring in :mod:`punt_lux.domain.hub.inbox`: the registry
owns *which* connection has an inbox, the inbox owns *what* a single connection's
queue does. The underlying ``SimpleQueue`` is itself thread-safe, so the inbox
carries no lock of its own; the registry's lock serializes only allocation and
lookup in its dict.
"""

from __future__ import annotations

import logging
import queue
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.protocol.messages.observer import ObserverMessage

logger = logging.getLogger(__name__)

__all__ = ["INBOX_CAPACITY", "BoundedInbox"]

# The most messages one inbox keeps before the oldest undelivered one is
# dropped. Mirrors the callback hold's ``_HOLD_CAPACITY``.
INBOX_CAPACITY = 32


@final
class BoundedInbox:
    """One connection's bounded FIFO of undelivered observer messages.

    Not independently locked: the underlying ``SimpleQueue`` is thread-safe for
    each operation, and the owning registry serializes allocation and lookup, so
    the inbox is a plain bounded container. The bound is a backstop against an
    undrained inbox, not a delivery quota -- when full, the oldest undelivered
    message is discarded so the newest is always admitted.
    """

    _connection_id: ConnectionId
    _capacity: int
    _queue: queue.SimpleQueue[ObserverMessage]
    __slots__ = ("_capacity", "_connection_id", "_queue")

    def __new__(
        cls, connection_id: ConnectionId, capacity: int = INBOX_CAPACITY
    ) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._capacity = capacity
        self._queue = queue.SimpleQueue()
        return self

    def put(self, message: ObserverMessage) -> None:
        """Enqueue ``message``; when full, drop and log the oldest undelivered one."""
        if self._queue.qsize() >= self._capacity:
            self._drop_oldest()
        self._queue.put(message)

    def _drop_oldest(self) -> None:
        """Discard the front message so a full inbox admits the newest; log the loss.

        The discarded message was fanned out to this session and never delivered,
        so -- like the callback hold reporting what it drops -- the loss is logged
        rather than silent: it is a message this inbox loses with nobody noticing.
        """
        try:
            dropped = self._queue.get_nowait()
        except queue.Empty:
            return
        logger.warning(
            "%s inbox full at %d; dropping undelivered observer message on %r",
            self._connection_id,
            self._capacity,
            dropped.topic,
        )

    def get(self, timeout: float) -> ObserverMessage | None:
        """Block up to ``timeout`` for the next message; ``None`` on timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> tuple[ObserverMessage, ...]:
        """Return every queued message in arrival order and clear the inbox."""
        drained: list[ObserverMessage] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                return tuple(drained)

    def depth(self) -> int:
        """Return the queued-but-undelivered count -- observational, per ``qsize()``."""
        return self._queue.qsize()
