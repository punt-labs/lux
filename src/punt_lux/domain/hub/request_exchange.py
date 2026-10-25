"""RequestExchange -- how one request of a kind holds the dial and waits for its reply.

A request locks its kind, writes on the dial it was made for, and waits for the one
reply that write elicits, from the dial's sink when a listener reads it and from the
dial's socket when none does. The reply carries no request id, so what keeps replies
and requests together is exclusion: one lock per reply kind, held across the write
and the wait, so at most one request of a kind is in flight on a dial. The locks
belong to the link, not to any one dial or request port, so every port made for a
dial, however many and however often, queues behind the same three.

Each request has two budgets, spent one after the other: the wait for its request
lock, and, once the lock is held, the wait for the reply, which gets its full
timeout from the send. A lock wait that spends its budget raises
:class:`DisplayBusyError`, sends nothing and retires nothing: another request of
the kind holds the dial, which says nothing of the display.

Lock order: a request lock, then the connection's state lock, then the dial's
socket lock, then the sink's lock; a caller holds at most one request lock.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.dial_ref import DialRef
from punt_lux.domain.hub.display_busy import DisplayBusyError

if TYPE_CHECKING:
    from collections.abc import Generator

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.display_replies import DisplayReplies
    from punt_lux.domain.hub.reply_sink import Pending
    from punt_lux.protocol import Message

__all__ = ["RequestExchange", "RequestKind"]

type RequestKind = Literal["ping", "scene", "query"]

# A ping's timestamp must exceed the last one's by at least this: the wall clock
# alone can repeat within a tick, and a pong is matched by the ts it echoes.
_TS_STEP = 1e-6


@final
class RequestExchange:
    """The locking, the waiting and the naming every request port shares."""

    _connection: DisplayConnection
    _replies: DisplayReplies
    _budget: float
    _locks: dict[RequestKind, threading.Lock]
    _last_ts: float
    __slots__ = ("_budget", "_connection", "_last_ts", "_locks", "_replies")

    def __new__(
        cls, connection: DisplayConnection, replies: DisplayReplies, budget: float
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._replies = replies
        self._budget = budget
        self._locks = {
            "ping": threading.Lock(),
            "scene": threading.Lock(),
            "query": threading.Lock(),
        }
        self._last_ts = 0.0
        return self

    def current(self) -> DialGeneration:
        """The dial a port made now is pinned to; raises if there is none."""
        return self._connection.require()

    @staticmethod
    def name(generation: DialGeneration) -> DialRef:
        """The name of ``generation``: the one place a dial is named for a caller."""
        return DialRef(generation)

    def next_ping_ts(self) -> float:
        """The timestamp for the next ping; the ping lock must be held.

        Raises ``RuntimeError`` otherwise: two pings stamping at once could repeat a
        timestamp, and a pong is matched by the ``ts`` it echoes.
        """
        if not self._locks["ping"].locked():
            msg = "a ping is stamped only while the ping lock is held"
            raise RuntimeError(msg)
        self._last_ts = max(time.time(), self._last_ts + _TS_STEP)
        return self._last_ts

    @contextlib.contextmanager
    def exclusive(
        self, kind: RequestKind, budget: float | None = None
    ) -> Generator[None]:
        """Hold the ``kind`` lock; busy if the wait for it spends ``budget``.

        Any interaction an inline wait decoded runs on this thread when the block
        ends, after the request lock and the reader slot are released.
        """
        lock = self._locks[kind]
        wait = self._budget if budget is None else budget
        if not lock.acquire(timeout=max(wait, 0.0)):
            msg = f"a {kind} request is already in flight"
            raise DisplayBusyError(msg)
        try:
            yield
        finally:
            lock.release()
            # Interactions an inline read held run here: no request lock, no slot.
            self._replies.run_held()

    def answer[R: Message](
        self,
        generation: DialGeneration,
        pending: Pending[object, R],
        budget: float | None = None,  # None: the standing budget
    ) -> R | None:
        """Wait ``budget`` for ``pending``'s reply on the dial the request went out on.

        The wait starts now, from the send: the time spent queued for the request
        lock was a separate budget.
        """
        wait = self._budget if budget is None else budget
        try:
            return self._replies.await_reply(
                generation, pending, time.monotonic() + wait
            )
        finally:
            generation.abandon(pending)

    def give_up(self, generation: DialGeneration) -> None:
        """Retire a dial whose query timed out, if it is still the current one."""
        self._connection.close_if_current(generation, cause="hub")
