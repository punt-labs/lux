"""ReplyWaiters -- who is waiting on a dial for a reply, and what they were sent.

A caller that writes a ping or a query waits for the display to answer, and a caller
that wants the ledger empty waits for the ack that empties it. This holds the three
in-flight slots (the ping, the query and the drained-ack wait), the tickets a caller
still waits on, and the answers not yet taken.

It owns no lock, and makes none: it works under the one
:class:`~punt_lux.domain.hub.owned_condition.OwnedCondition` its
:class:`~punt_lux.domain.hub.reply_sink.ReplySink` passes in. A Hub request or a
recorded end must refuse the next wait and fail every pending one in one step, and a
second lock would make that two steps; the sink's lock order is left as it was. The
condition need not be re-entrant, and the sink gives it one that is not: a public
method that takes the lock never calls another that does, and the ``*_locked`` methods
are the bodies the sink runs while it already holds the lock for a step of its own.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.hub.owned_condition import OwnedCondition
from punt_lux.domain.hub.pending import Pending
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_end import DialEnd
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ReplyOutOfOrderError", "ReplyWaiters"]


class ReplyOutOfOrderError(ValueError):
    """A reply matched nothing the display owes: the stream has skewed."""


@final
class ReplyWaiters:
    """What a dial is waited on for, under the sink's one lock."""

    _cond: OwnedCondition
    _end: DialEnd
    # PY-TS-14 OK: None while no ping is in flight; at most one is, and it names it.
    _ping: Pending[float, PongMessage] | None
    # PY-TS-14 OK: None while no query is in flight.
    _query: Pending[None, QueryResponse] | None
    # PY-TS-14 OK: None while nobody waits for the ledger to empty.
    _drained: Pending[None, AckMessage] | None
    _waiting: set[object]  # tickets a caller still waits on
    _answers: dict[object, Message]  # replies not yet taken
    __slots__ = (
        "_answers",
        "_cond",
        "_drained",
        "_end",
        "_ping",
        "_query",
        "_waiting",
    )

    def __new__(cls, cond: OwnedCondition, end: DialEnd) -> Self:
        self = super().__new__(cls)
        self._cond = cond
        self._end = end
        self._ping = None
        self._query = None
        self._drained = None
        self._waiting = set()
        self._answers = {}
        return self

    def expect_pong(self, ts: float) -> Pending[float, PongMessage]:
        """Record the ping in flight; only a pong echoing ``ts`` answers it."""
        pending = Pending(ts, PongMessage)
        with self._cond:
            self._require_live_locked()
            self._require_free(self._ping, "a ping")
            self._ping = pending
            self._waiting.add(pending)
        return pending

    def expect_query(self) -> Pending[None, QueryResponse]:
        """Record the query in flight; the next query response answers it."""
        pending = Pending(None, QueryResponse)
        with self._cond:
            self._require_live_locked()
            self._require_free(self._query, "a query")
            self._query = pending
            self._waiting.add(pending)
        return pending

    # PY-TS-14 OK: None is a ledger already empty: there is nothing to wait for.
    def expect_drained_locked(self, *, owed: bool) -> Pending[None, AckMessage] | None:
        """Record a wait for the ledger to empty; ``None`` if nothing is owed.

        The caller holds the lock and says whether the ledger holds anything; the ack
        that empties it answers the wait (:meth:`ledger_emptied_locked`).
        """
        self._require_held()
        self._require_live_locked()
        if not owed:
            return None
        self._require_free(self._drained, "an ack wait")
        pending = Pending(None, AckMessage)
        self._drained = pending
        self._waiting.add(pending)
        return pending

    # PY-TS-14 OK: None is the timeout; an end of the dial raises instead.
    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply, taking it; or ``None``.

        Raises :class:`ConnectionClosedError` the moment the dial is ended.
        """
        with self._cond:
            self._cond.wait_for(
                lambda: pending in self._answers or self._end.closing is not None,
                max(timeout, 0.0),
            )
            reply = self._answers.pop(pending, None)
            if isinstance(reply, pending.kind):
                return reply
            self._require_live_locked()
            return None

    def answered(self, pending: Pending[object, Message]) -> bool:
        """Whether ``pending``'s reply has arrived and is waiting to be taken."""
        with self._cond:
            return pending in self._answers

    def abandon(self, pending: Pending[object, Message]) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        with self._cond:
            self._waiting.discard(pending)
            self._answers.pop(pending, None)
            if self._ping is pending:
                self._ping = None
            if self._query is pending:
                self._query = None
            if self._drained is pending:
                self._drained = None

    def deliver_pong_locked(self, pong: PongMessage) -> None:
        """Answer the ping in flight if ``pong`` echoes it; a stray is dropped."""
        self._require_held()
        ping = self._ping
        if ping is None or ping.key != pong.ts:
            logger.debug("dropping a pong for ts %s: no such ping in flight", pong.ts)
            return
        self._hand_over_locked(ping, pong)
        self._ping = None

    def deliver_query_locked(self, response: QueryResponse) -> None:
        """Answer the query in flight; none in flight is a skewed stream."""
        self._require_held()
        query = self._query
        if query is None:
            what = response.method
            msg = f"query response for {what!r} arrived with none in flight"
            raise ReplyOutOfOrderError(msg)
        self._hand_over_locked(query, response)
        self._query = None

    def ledger_emptied_locked(self, ack: AckMessage) -> None:
        """Answer the wait for the ledger to empty, if there is one, with ``ack``."""
        self._require_held()
        drained = self._drained
        if drained is not None:
            self._hand_over_locked(drained, ack)
            self._drained = None

    def fail_all_locked(self) -> None:
        """Forget every ticket and wake every waiter: the dial is ending."""
        self._require_held()
        self._ping = None
        self._query = None
        self._drained = None
        self._waiting.clear()
        self._cond.notify_all()

    def _require_held(self) -> None:
        """Raise unless this thread holds the sink's lock."""
        if not self._cond.held_here():
            msg = "a *_locked method of the reply waiters ran without the sink's lock"
            raise LockDisciplineError(msg)

    def _require_live_locked(self) -> None:
        """Raise once the dial is ending; the caller holds the lock."""
        if self._end.closing is not None:
            msg = "the display connection closed while a reply was pending"
            raise ConnectionClosedError(msg)

    def _hand_over_locked(
        self, pending: Pending[object, Message], reply: Message
    ) -> None:
        """Keep ``reply`` for its waiter; a ticket nobody waits on keeps nothing."""
        if pending in self._waiting:
            self._answers[pending] = reply

    @staticmethod
    def _require_free(
        slot: Pending[float, PongMessage]
        | Pending[None, QueryResponse]
        | Pending[None, AckMessage]
        | None,  # PY-TS-14 OK: None is a free slot
        what: str,
    ) -> None:
        if slot is not None:
            msg = f"{what} is already in flight on this dial"
            raise RuntimeError(msg)
