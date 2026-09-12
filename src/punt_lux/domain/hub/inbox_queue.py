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
queue does. The bounded admission is a compound check-then-act
(``qsize`` -> ``_drop_oldest`` -> ``put``) and the inbox has two unsynchronized
producers -- the ``Hub.publish`` writer closure (which runs ``put`` outside the
registry lock) and ``offer`` (which runs ``put`` inside it) -- so the inbox
carries its OWN leaf lock to make that sequence atomic. The registry's lock is a
separate concern: it serializes allocation and lookup in its dict.
"""

from __future__ import annotations

import logging
import queue
import threading
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

    Independently locked by a leaf ``threading.Lock``. The bounded admission is a
    compound check-then-act -- ``qsize()`` decides whether ``_drop_oldest()`` runs
    before ``put()`` -- and two producers reach it without a shared outer lock: the
    ``Hub.publish`` writer closure fans out with no registry lock held, while
    ``offer`` holds the registry lock. Guarding the compound sequence under this
    inbox's own lock makes it self-synchronizing regardless of which producer
    calls it, so the bound is EXACT under concurrency: the queue never exceeds
    ``capacity``, and one over-capacity admission drops exactly one oldest
    message, never two. It is a backstop against an undrained inbox, not a
    delivery quota -- when full, the oldest undelivered message is discarded so
    the newest is always admitted.

    Lock discipline. ``_lock`` is a strict LEAF: every acquirer touches only the
    queue and the logger while holding it, and acquires no other lock -- so no
    cycle can form. The acquiring sites are exactly the mutators and observers on
    this class: ``put`` (which calls ``_drop_oldest`` while already holding the
    lock -- a plain call, never a re-acquire), ``drain``, and ``depth``. ``get``
    does NOT take the lock: a blocking dequeue must never hold a lock across its
    wait, or it would stall every producer for the whole timeout -- the very
    producers that would satisfy the wait -- and ``SimpleQueue.get`` is already
    atomic, participating in no check-then-act. The one place ``_lock`` nests
    under another lock is ``inbox.offer``: ``_inboxes_lock`` -> ``BoundedInbox._lock``,
    one-way and never reversed (nothing here reaches back for ``_inboxes_lock``),
    so the order is acyclic and deadlock-free -- the same structure proved for
    the D3 edge.
    """

    _connection_id: ConnectionId
    _capacity: int
    _queue: queue.SimpleQueue[ObserverMessage]
    _lock: threading.Lock
    __slots__ = ("_capacity", "_connection_id", "_lock", "_queue")

    def __new__(
        cls, connection_id: ConnectionId, capacity: int = INBOX_CAPACITY
    ) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._capacity = capacity
        self._queue = queue.SimpleQueue()
        self._lock = threading.Lock()
        return self

    def put(self, message: ObserverMessage) -> None:
        """Enqueue ``message``; when full, drop and log the oldest undelivered one.

        The ``qsize`` check, the conditional ``_drop_oldest``, and the ``put`` are
        one compound act held under ``_lock`` so two producers can neither both
        skip the drop and overshoot the cap, nor both drop for one admission and
        discard two messages.
        """
        with self._lock:
            if self._queue.qsize() >= self._capacity:
                self._drop_oldest()
            self._queue.put(message)

    def _drop_oldest(self) -> None:
        """Discard the front message so a full inbox admits the newest; log the loss.

        The caller (``put``) already holds ``_lock``; this never re-acquires it.
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
        """Block up to ``timeout`` for the next message; ``None`` on timeout.

        Deliberately outside ``_lock``: a blocking dequeue must not hold the leaf
        lock across its wait (see the class docstring's lock discipline).
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None  # None == wait timed out; a normal poll outcome

    def drain(self) -> tuple[ObserverMessage, ...]:
        """Return every queued message in arrival order and clear the inbox."""
        with self._lock:
            drained: list[ObserverMessage] = []
            while True:
                try:
                    drained.append(self._queue.get_nowait())
                except queue.Empty:
                    return tuple(drained)

    def depth(self) -> int:
        """Return the queued-but-undelivered count -- observational, per ``qsize()``."""
        with self._lock:
            return self._queue.qsize()
