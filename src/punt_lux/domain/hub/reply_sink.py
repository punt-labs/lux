"""ReplySink -- what one dial is owed by the display, and who is waiting for it.

A reply carries no request id. It is matched to its request by what the wire does
carry: a pong by the ``ts`` of the ping in flight, an ack by its position among the
acks owed (the scene ids repeat, so the id is only a cross-check), a query response
by being the one query in flight. Nobody waits for an ack: it only settles the
ledger. The sink holds what a caller is waiting for and the acks still owed, so it
is bounded by the scenes written, not by the replies received.

What the display owes is known exactly: the ledger is entered under the socket lock
before the reader can see the matching bytes, and a query that gives up retires its
dial. So an ack with none owed, or a query response with none in flight, is not a
late arrival but a stream that has skewed, and ends the dial like any other
out-of-order reply. A late pong is the one legitimate stray: a ping that timed out
keeps its dial, and the pong is dropped by its ``ts``.

One sink belongs to one generation (:class:`~punt_lux.domain.hub.dial_generation.
DialGeneration`) and goes with it: discarding the sink fails every waiter and
refuses every later delivery. The sink also owns the generation's end: who ended it
is recorded in the same hold that refuses deliveries, so no reply is parked after the
dial reads as closed. What the display still owed when it ended is the ledger, the
evidence of a death.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["REPLY_TYPES", "Pending", "ReplyOutOfOrderError", "ReplySink"]

REPLY_TYPES = (AckMessage, PongMessage, QueryResponse)


class ReplyOutOfOrderError(ValueError):
    """A reply matched nothing the display owes: the stream has skewed."""


@final
class Pending[K, R: Message]:
    """A ticket for one reply a sink owes: what it must echo, and what it will be.

    Opaque to everyone but the sink that issued it, which keeps the reply and
    whether a caller still waits; a holder can only give it back to that sink.
    """

    _key: K
    _kind: type[R]
    __slots__ = ("_key", "_kind")

    def __new__(cls, key: K, kind: type[R]) -> Self:
        self = super().__new__(cls)
        self._key = key
        self._kind = kind
        return self

    @property
    def key(self) -> K:
        """What the reply must echo: a ping's ``ts``, an ack's scene id."""
        return self._key

    @property
    def kind(self) -> type[R]:
        """The type of the reply that answers it."""
        return self._kind


@final
class ReplySink:
    """The replies one dial is owed: acks in write order, a ping, a query."""

    _cond: threading.Condition
    _acks: deque[SceneId]  # scenes written and not yet acked, in wire order
    _ping: Pending[float, PongMessage] | None  # the one ping in flight
    _query: Pending[None, QueryResponse] | None  # the one query in flight
    _waiting: set[object]  # tickets a caller still waits on
    _answers: dict[object, Message]  # replies not yet taken
    _ended: RetireCause | None  # None while live; once discarded, who ended it
    __slots__ = (
        "_acks",
        "_answers",
        "_cond",
        "_ended",
        "_ping",
        "_query",
        "_waiting",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._acks = deque()
        self._ping = None
        self._query = None
        self._waiting = set()
        self._answers = {}
        self._ended = None
        return self

    @property
    def ended(self) -> RetireCause | None:
        """Who ended the sink's dial; ``None`` while it is live."""
        with self._cond:
            return self._ended

    @property
    def owed_acks(self) -> int:
        """How many acks the display still owes: the bound on the sink."""
        with self._cond:
            return len(self._acks)

    def owe_ack(self, scene_id: str) -> None:
        """Record a scene written to the display, in wire order."""
        with self._cond:
            self._require_live()
            self._acks.append(SceneId(scene_id))

    def expect_pong(self, ts: float) -> Pending[float, PongMessage]:
        """Record the ping in flight; only a pong echoing ``ts`` answers it."""
        pending = Pending(ts, PongMessage)
        with self._cond:
            self._require_live()
            self._require_free(self._ping, "ping")
            self._ping = pending
            self._waiting.add(pending)
        return pending

    def expect_query(self) -> Pending[None, QueryResponse]:
        """Record the query in flight; the next query response answers it."""
        pending = Pending(None, QueryResponse)
        with self._cond:
            self._require_live()
            self._require_free(self._query, "query")
            self._query = pending
            self._waiting.add(pending)
        return pending

    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply, taking it; or ``None``.

        Raises :class:`ConnectionClosedError` the moment the sink is discarded.
        """
        with self._cond:
            self._cond.wait_for(
                lambda: self._holds(pending) or self._ended is not None,
                max(timeout, 0.0),
            )
            reply = self._answers.pop(pending, None)
            if isinstance(reply, pending.kind):
                return reply
            self._require_live()
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

    def deliver(self, msg: Message) -> None:
        """Hand an arrived reply to the request it answers.

        A discarded sink parks no reply: nobody waits on a retired dial's answers.
        An interaction the dial read is not a reply, and is the link's to run.
        Raises :class:`ReplyOutOfOrderError` for an ack or a query response that
        matches nothing owed.
        """
        with self._cond:
            if self._ended is not None:
                return
            if isinstance(msg, AckMessage):
                self._deliver_ack(msg)
            elif isinstance(msg, PongMessage):
                self._deliver_pong(msg)
            elif isinstance(msg, QueryResponse):
                self._deliver_query(msg)
            self._cond.notify_all()

    def discard(self, cause: RetireCause) -> tuple[SceneId, ...]:
        """End the sink with its dial: record who ended it, fail every waiter.

        The first call wins and returns the ledger: the ids of the scenes the display
        still owed an ack for, in write order. Any later call returns nothing. A reply
        already handed over stays for its waiter to take: it arrived before the
        retirement. The ``ended`` mark and the refusal of deliveries are one hold.
        """
        with self._cond:
            if self._ended is not None:
                return ()
            self._ended = cause
            owed = tuple(self._acks)
            self._acks.clear()
            self._ping = None
            self._query = None
            self._waiting.clear()
            self._cond.notify_all()
            return owed

    def _holds(self, pending: Pending[object, Message]) -> bool:
        return pending in self._answers

    def _require_live(self) -> None:
        if self._ended is not None:
            msg = "the display connection closed while a reply was pending"
            raise ConnectionClosedError(msg)

    @staticmethod
    def _require_free(
        slot: Pending[float, PongMessage] | Pending[None, QueryResponse] | None,
        what: str,
    ) -> None:
        if slot is not None:
            msg = f"a {what} is already in flight on this dial"
            raise RuntimeError(msg)

    def _deliver_ack(self, ack: AckMessage) -> None:
        if not self._acks:
            msg = f"ack for {ack.scene_id!r} arrived when none was owed"
            raise ReplyOutOfOrderError(msg)
        owed = self._acks.popleft()
        if owed != ack.scene_id:
            msg = f"ack for {ack.scene_id!r} arrived where {owed!r} was owed"
            raise ReplyOutOfOrderError(msg)

    def _deliver_pong(self, pong: PongMessage) -> None:
        ping = self._ping
        if ping is None or ping.key != pong.ts:
            logger.debug("dropping a pong for ts %s: no such ping in flight", pong.ts)
            return
        self._hand_over(ping, pong)
        self._ping = None

    def _deliver_query(self, response: QueryResponse) -> None:
        query = self._query
        if query is None:
            msg = f"query response for {response.method!r} arrived with none in flight"
            raise ReplyOutOfOrderError(msg)
        self._hand_over(query, response)
        self._query = None

    def _hand_over(self, pending: Pending[object, Message], reply: Message) -> None:
        """Keep ``reply`` for its waiter; a ticket nobody waits on keeps nothing."""
        if pending in self._waiting:
            self._answers[pending] = reply
