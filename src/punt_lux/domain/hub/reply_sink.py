"""ReplySink -- what one dial is owed by the display, and who is waiting for it.

A reply carries no request id. It is matched to its request by what the wire does
carry: a pong by the ``ts`` of the ping in flight, an ack by its position among the
acks owed (the scene ids repeat, so the id is only a cross-check), a query response
by being the one query in flight. A reply that matches nothing is dropped on arrival,
so the sink holds only what a caller is waiting for or an ack still owed: it is
bounded by the scenes written, not by the replies received.

One sink belongs to one generation (:class:`~punt_lux.domain.hub.dial_generation.
DialGeneration`) and goes with it: discarding the sink fails every waiter.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["REPLY_TYPES", "Pending", "ReplyOutOfOrderError", "ReplySink"]

REPLY_TYPES = (AckMessage, PongMessage, QueryResponse)


class ReplyOutOfOrderError(ValueError):
    """An ack named another scene than the oldest one owed: the stream has skewed."""


@final
class Pending:
    """One reply a caller may be waiting for, and the reply once it has come."""

    _key: object
    _awaited: bool
    _reply: Message | None  # None until the matching reply arrives
    __slots__ = ("_awaited", "_key", "_reply")

    def __new__(cls, key: object, *, awaited: bool = True) -> Self:
        self = super().__new__(cls)
        self._key = key
        self._awaited = awaited
        self._reply = None
        return self

    @property
    def reply(self) -> Message | None:
        """The matching reply, or ``None`` if it has not arrived."""
        return self._reply

    @property
    def key(self) -> object:
        """What the reply must echo: a ping's ``ts``, an ack's scene id."""
        return self._key

    @property
    def is_awaited(self) -> bool:
        """Whether a caller is waiting for this reply, so it is to be delivered."""
        return self._awaited

    def give_up(self) -> None:
        """Stop waiting: the reply, if it comes, is dropped (an ack still pops)."""
        self._awaited = False

    def fulfil(self, reply: Message) -> None:
        """Hand the reply over."""
        self._reply = reply


@final
class ReplySink:
    """The replies one dial is owed: acks in write order, a ping, a query."""

    _cond: threading.Condition
    _acks: deque[Pending]
    _ping: Pending | None  # the one ping in flight, None between pings
    _query: Pending | None  # the one query in flight, None between queries
    _discarded: bool
    __slots__ = ("_acks", "_cond", "_discarded", "_ping", "_query")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._acks = deque()
        self._ping = None
        self._query = None
        self._discarded = False
        return self

    @property
    def owed_acks(self) -> int:
        """How many acks the display still owes: the bound on the sink."""
        with self._cond:
            return len(self._acks)

    def owe_ack(self, scene_id: str, *, awaited: bool) -> Pending:
        """Record a scene written to the display, in wire order."""
        owed = Pending(scene_id, awaited=awaited)
        with self._cond:
            self._require_live()
            self._acks.append(owed)
        return owed

    def expect_pong(self, ts: float) -> Pending:
        """Record the ping in flight; only a pong echoing ``ts`` answers it."""
        pending = Pending(ts)
        with self._cond:
            self._require_live()
            self._ping = pending
        return pending

    def expect_query(self) -> Pending:
        """Record the query in flight; the next query response answers it."""
        pending = Pending(None)
        with self._cond:
            self._require_live()
            self._query = pending
        return pending

    def await_reply(self, pending: Pending, timeout: float) -> Message | None:
        """Wait up to ``timeout`` for ``pending``'s reply, or ``None``.

        Raises :class:`ConnectionClosedError` the moment the sink is discarded.
        """
        with self._cond:
            self._cond.wait_for(
                lambda: pending.reply is not None or self._discarded,
                max(timeout, 0.0),
            )
            if pending.reply is not None:
                return pending.reply
            self._require_live()
            return None

    def abandon(self, pending: Pending) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        with self._cond:
            pending.give_up()
            if self._ping is pending:
                self._ping = None
            if self._query is pending:
                self._query = None

    def deliver(self, msg: Message) -> None:
        """Hand an arrived reply to the request it answers, or drop it.

        Raises :class:`ReplyOutOfOrderError` for an ack that names another scene
        than the oldest one owed.
        """
        with self._cond:
            if isinstance(msg, AckMessage):
                self._deliver_ack(msg)
            elif isinstance(msg, PongMessage):
                self._deliver_pong(msg)
            elif isinstance(msg, QueryResponse):
                self._deliver_query(msg)
            self._cond.notify_all()

    def discard(self) -> None:
        """End the sink with its dial: drop what is owed and fail every waiter."""
        with self._cond:
            self._discarded = True
            self._acks.clear()
            self._ping = None
            self._query = None
            self._cond.notify_all()

    def _require_live(self) -> None:
        if self._discarded:
            msg = "the display connection closed while a reply was pending"
            raise ConnectionClosedError(msg)

    def _deliver_ack(self, ack: AckMessage) -> None:
        if not self._acks:
            logger.debug("dropping an ack for %r: none is owed", ack.scene_id)
            return
        owed = self._acks.popleft()
        if owed.key != ack.scene_id:
            msg = f"ack for {ack.scene_id!r} arrived where {owed.key!r} was owed"
            raise ReplyOutOfOrderError(msg)
        if owed.is_awaited:
            owed.fulfil(ack)

    def _deliver_pong(self, pong: PongMessage) -> None:
        ping = self._ping
        if ping is None or ping.key != pong.ts:
            logger.debug("dropping a pong for ts %s: no such ping in flight", pong.ts)
            return
        ping.fulfil(pong)
        self._ping = None

    def _deliver_query(self, response: QueryResponse) -> None:
        query = self._query
        if query is None:
            logger.debug("dropping a query response for %r: none in flight", response)
            return
        query.fulfil(response)
        self._query = None
