"""ReplyWaiters -- who is waiting on a dial for a reply, and what they were sent.

A caller that writes a ping or a query waits for the display to answer; this holds
the one ping and the one query in flight, the tickets a caller still waits on, and
the answers not yet taken. It owns no lock: it works under the one
:class:`threading.Condition` its :class:`~punt_lux.domain.hub.reply_sink.ReplySink`
passes in, and never makes one of its own. A Hub request or a recorded end must
refuse the next wait and fail every pending one in one step, and two locks would
make that two steps; the sink's lock order is also left as it was.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.pending import Pending
from punt_lux.protocol import PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_end import DialEnd
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ReplyOutOfOrderError", "ReplyWaiters"]


class ReplyOutOfOrderError(ValueError):
    """A reply matched nothing the display owes: the stream has skewed."""


@final
class ReplyWaiters:
    """The pong and the query a dial is waited on for, under the sink's one lock."""

    _cond: threading.Condition
    _end: DialEnd
    _ping: Pending[float, PongMessage] | None  # the one ping in flight
    _query: Pending[None, QueryResponse] | None  # the one query in flight
    _waiting: set[object]  # tickets a caller still waits on
    _answers: dict[object, Message]  # replies not yet taken
    __slots__ = ("_answers", "_cond", "_end", "_ping", "_query", "_waiting")

    def __new__(cls, cond: threading.Condition, end: DialEnd) -> Self:
        self = super().__new__(cls)
        self._cond = cond
        self._end = end
        self._ping = None
        self._query = None
        self._waiting = set()
        self._answers = {}
        return self

    def expect_pong(self, ts: float) -> Pending[float, PongMessage]:
        """Record the ping in flight; only a pong echoing ``ts`` answers it."""
        pending = Pending(ts, PongMessage)
        with self._cond:
            self.require_live()
            self._require_free(self._ping, "ping")
            self._ping = pending
            self._waiting.add(pending)
        return pending

    def expect_query(self) -> Pending[None, QueryResponse]:
        """Record the query in flight; the next query response answers it."""
        pending = Pending(None, QueryResponse)
        with self._cond:
            self.require_live()
            self._require_free(self._query, "query")
            self._query = pending
            self._waiting.add(pending)
        return pending

    def watch(self, pending: Pending[object, Message]) -> None:
        """Wait on a ticket the ledger issued, failed and abandoned like the rest."""
        with self._cond:
            self._waiting.add(pending)

    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply, taking it; or ``None``.

        Raises :class:`ConnectionClosedError` the moment the dial is ended.
        """
        with self._cond:
            self._cond.wait_for(
                lambda: self._holds(pending) or self._end.closing is not None,
                max(timeout, 0.0),
            )
            reply = self._answers.pop(pending, None)
            if isinstance(reply, pending.kind):
                return reply
            self.require_live()
            return None

    def answered(self, pending: Pending[object, Message]) -> bool:
        """Whether ``pending``'s reply has arrived and is waiting to be taken."""
        with self._cond:
            return self._holds(pending)

    def abandon(self, pending: Pending[object, Message]) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        with self._cond:
            self._waiting.discard(pending)
            self._answers.pop(pending, None)
            if self._ping is pending:
                self._ping = None
            if self._query is pending:
                self._query = None

    def hand_over(self, pending: Pending[object, Message], reply: Message) -> None:
        """Keep ``reply`` for its waiter; a ticket nobody waits on keeps nothing."""
        with self._cond:
            if pending in self._waiting:
                self._answers[pending] = reply

    def deliver_pong(self, pong: PongMessage) -> None:
        """Answer the ping in flight if ``pong`` echoes it; a stray is dropped."""
        with self._cond:
            ping = self._ping
            if ping is None or ping.key != pong.ts:
                logger.debug(
                    "dropping a pong for ts %s: no such ping in flight", pong.ts
                )
                return
            self.hand_over(ping, pong)
            self._ping = None

    def deliver_query(self, response: QueryResponse) -> None:
        """Answer the query in flight; none in flight is a skewed stream."""
        with self._cond:
            query = self._query
            if query is None:
                what = response.method
                msg = f"query response for {what!r} arrived with none in flight"
                raise ReplyOutOfOrderError(msg)
            self.hand_over(query, response)
            self._query = None

    def fail_all(self) -> None:
        """Forget every ticket and wake every waiter: the dial is ending."""
        with self._cond:
            self._ping = None
            self._query = None
            self._waiting.clear()
            self._cond.notify_all()

    def require_live(self) -> None:
        """Raise :class:`ConnectionClosedError` once the dial is ending."""
        if self._end.closing is not None:
            msg = "the display connection closed while a reply was pending"
            raise ConnectionClosedError(msg)

    def _holds(self, pending: Pending[object, Message]) -> bool:
        return pending in self._answers

    @staticmethod
    def _require_free(
        slot: Pending[float, PongMessage] | Pending[None, QueryResponse] | None,
        what: str,
    ) -> None:
        if slot is not None:
            msg = f"a {what} is already in flight on this dial"
            raise RuntimeError(msg)
