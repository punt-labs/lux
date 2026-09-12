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
queue does. Bounded admission is a compound act -- ``len`` decides whether the
oldest is dropped before the newest is appended -- and both producers *and* the
consumer reach the same deque without a shared outer lock: the ``Hub.publish``
writer closure and ``offer`` produce, ``recv`` consumes. So the inbox owns a
:class:`threading.Condition` and every operation runs under its lock, which makes
the compound atomic against a concurrent consumer as well as a concurrent
producer. The registry's lock is a separate concern: it serializes allocation
and lookup in its dict.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
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

    Synchronized by its own :class:`threading.Condition`. Bounded admission is a
    compound check-then-act -- ``len()`` decides whether the oldest is dropped
    before the newest is appended -- and three parties reach the deque without a
    shared outer lock: the ``Hub.publish`` writer closure produces with no
    registry lock held, ``offer`` produces holding the registry lock, and the
    ``recv`` consumer takes. Running every operation under the condition makes the
    compound atomic against a concurrent consumer as well as a concurrent
    producer, so the bound is EXACT: the queue never exceeds ``capacity``, one
    over-capacity admission drops exactly one oldest message (never zero, and
    never two), and a consumer that makes room can never be shadowed by a drop
    decided against a stale full-check. It is a backstop against an undrained
    inbox, not a delivery quota -- when full, the oldest undelivered message is
    discarded so the newest is always admitted.

    Lock discipline. The condition's lock is a strict LEAF: every holder touches
    only the deque and the logger, and acquires no other lock. ``get`` blocks on
    ``Condition.wait``, which RELEASES the lock while waiting and reacquires it
    only to recheck -- so the blocking wait holds no lock, and a producer is never
    stalled behind a waiting consumer. The one place the condition's lock nests
    under another lock is ``inbox.offer``: ``_inboxes_lock`` -> the condition's
    lock, one-way and never reversed (nothing here reaches back for
    ``_inboxes_lock``), so the order is acyclic and deadlock-free -- the structure
    jms's model-check verified.
    """

    _connection_id: ConnectionId
    _capacity: int
    _queue: deque[ObserverMessage]
    _cond: threading.Condition
    __slots__ = ("_capacity", "_cond", "_connection_id", "_queue")

    def __new__(
        cls, connection_id: ConnectionId, capacity: int = INBOX_CAPACITY
    ) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._capacity = capacity
        self._queue = deque()
        self._cond = threading.Condition()
        return self

    def put(self, message: ObserverMessage) -> None:
        """Enqueue ``message``; when full, drop and log the oldest undelivered one.

        The ``len`` check, the conditional drop, and the append are one compound
        act held under the condition, so neither a racing producer nor a racing
        consumer can slip between the check and the drop: two producers can
        neither overshoot the cap nor double-drop, and a consumer that dequeues
        cannot be shadowed by a drop decided against a now-stale full-check.
        """
        with self._cond:
            if len(self._queue) >= self._capacity:
                self._drop_oldest()
            self._queue.append(message)
            self._cond.notify()

    def _drop_oldest(self) -> None:
        """Discard the front message so a full inbox admits the newest; log the loss.

        The caller holds the condition; this never re-enters it beyond the
        reentrant hold it already has. The discarded message was fanned out to
        this session and never delivered, so -- like the callback hold reporting
        what it drops -- the loss is logged rather than silent: it is a message
        this inbox loses with nobody noticing.
        """
        if not self._queue:
            return
        dropped = self._queue.popleft()
        logger.warning(
            "%s inbox full at %d; dropping undelivered observer message on %r",
            self._connection_id,
            self._capacity,
            dropped.topic,
        )

    def get(self, timeout: float) -> ObserverMessage | None:
        """Block up to ``timeout`` for the next message; ``None`` on timeout.

        The dequeue is serialized with ``put``'s compound under the condition, but
        ``Condition.wait`` releases the lock while blocking (via ``wait_for``), so
        the wait stalls no producer and holds no lock across the block.
        """
        with self._cond:
            if self._cond.wait_for(lambda: len(self._queue) > 0, timeout):
                return self._queue.popleft()
            return None  # None == wait timed out; a normal poll outcome

    def drain(self) -> tuple[ObserverMessage, ...]:
        """Return every queued message in arrival order and clear the inbox."""
        with self._cond:
            drained = tuple(self._queue)
            self._queue.clear()
            return drained

    def depth(self) -> int:
        """Return the queued-but-undelivered count -- observational, per ``len()``."""
        with self._cond:
            return len(self._queue)
