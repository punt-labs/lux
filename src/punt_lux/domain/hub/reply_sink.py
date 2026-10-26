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
DialGeneration`) and goes with it. A dial's end has three steps, and they are separate:

1. A display or unresponsive end is *recorded* (:meth:`~ReplySink.end`): the first
   cause wins. A Hub end is only *requested* (:meth:`~ReplySink.request_hub`) and
   records nothing, since the display may have died already and the Hub cannot tell
   until its reader has looked. Either way writes are refused and every waiter fails
   at once, but the ledger is left alone and an ack is still applied: the display
   sent it before the dial ended, so it is evidence that the scene survived.
2. :meth:`~ReplySink.decide` fixes the cause once the dial's reader has read to the
   point where it would block: the end of file it saw is the display's, else a Hub
   request is the Hub's, else the cause recorded stands.
3. :meth:`~ReplySink.capture` takes the ledger, the scenes the display still owed.
   After it nothing is delivered, and whoever waits to see the dial settled is woken.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_end import DialEnd
from punt_lux.domain.hub.pending import Pending
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError, ReplyWaiters
from punt_lux.domain.hub.settlement import Settlement
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import AckMessage, PongMessage, QueryResponse

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.protocol import Message

__all__ = ["REPLY_TYPES", "ReplySink"]

REPLY_TYPES = (AckMessage, PongMessage, QueryResponse)


@final
class ReplySink:
    """The replies one dial is owed: acks in write order, a ping, a query."""

    _cond: threading.Condition
    _acks: deque[SceneId]  # scenes written and not yet acked, in wire order
    _waiters: ReplyWaiters  # what callers wait on, under this sink's lock
    _end: DialEnd  # the first cause recorded, and the Hub's request
    _captured: bool  # the ledger has been taken
    _acked: bool  # an ack was applied on this dial
    __slots__ = (
        "_acked",
        "_acks",
        "_captured",
        "_cond",
        "_end",
        "_waiters",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        # A lock that cannot be re-entered: ReplyWaiters never takes it twice, and a
        # re-entry would be a deadlock a test catches, not a hidden dependence.
        self._cond = threading.Condition(threading.Lock())
        self._acks = deque()
        self._end = DialEnd()
        self._waiters = ReplyWaiters(self._cond, self._end)
        self._captured = False
        self._acked = False
        return self

    @property
    # PY-TS-14 OK: None until a cause is recorded or decided: the dial may be open.
    def ended(self) -> RetireCause | None:
        """The first cause recorded for the dial's end; ``None`` while none is."""
        with self._cond:
            return self._end.cause

    @property
    # PY-TS-14 OK: None while nothing is ending the dial: no cause, no Hub request.
    def closing(self) -> RetireCause | None:
        """Who is ending the dial: the recorded cause, else ``hub`` once it asked.

        What a refused write or a failed waiter reports: not a decided cause.
        """
        with self._cond:
            return self._end.closing

    @property
    def captured(self) -> bool:
        """Whether the ledger has been taken: nothing more is delivered."""
        with self._cond:
            return self._captured

    @property
    def owed_acks(self) -> int:
        """How many acks the display still owes: the bound on the sink."""
        with self._cond:
            return len(self._acks)

    def owe_ack(self, scene_id: str) -> None:
        """Record a scene written to the display, in wire order.

        The bytes are on the wire, so the scene is owed whatever the end state: a Hub
        request or a recorded cause does not refuse it. Only a captured dial does,
        its ledger having been taken: the scene is then not recorded and the writer
        reports the failure.
        """
        with self._cond:
            if self._captured:
                msg = "the display connection closed before the scene was recorded"
                raise ConnectionClosedError(msg)
            self._acks.append(SceneId(scene_id))

    def expect_pong(self, ts: float) -> Pending[float, PongMessage]:
        """Record the ping in flight; only a pong echoing ``ts`` answers it."""
        return self._waiters.expect_pong(ts)

    def expect_query(self) -> Pending[None, QueryResponse]:
        """Record the query in flight; the next query response answers it."""
        return self._waiters.expect_query()

    # PY-TS-14 OK: None is a ledger already empty: there is nothing to wait for.
    def expect_drained(self) -> Pending[None, AckMessage] | None:
        """Record a wait for the ledger to empty; ``None`` if nothing is owed already.

        The ack that empties the ledger answers it: the display has then taken, and
        swapped past, every scene written to this dial.
        """
        with self._cond:
            return self._waiters.expect_drained_locked(owed=bool(self._acks))

    # PY-TS-14 OK: None is the timeout; an end of the dial raises instead.
    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply, taking it; or ``None``.

        Raises :class:`ConnectionClosedError` the moment the dial is ended.
        """
        return self._waiters.await_reply(pending, timeout)

    def await_captured(self, timeout: float) -> bool:
        """Wait up to ``timeout`` for the ledger to be taken; whether it was.

        Holds nothing but the sink's own lock, and releases it while it waits.
        """
        with self._cond:
            return self._cond.wait_for(lambda: self._captured, max(timeout, 0.0))

    def answered(self, pending: Pending[object, Message]) -> bool:
        """Whether ``pending``'s reply has arrived and is waiting to be taken."""
        return self._waiters.answered(pending)

    def abandon(self, pending: Pending[object, Message]) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        self._waiters.abandon(pending)

    def deliver(self, msg: Message) -> None:
        """Hand an arrived reply to the request it answers.

        An ack is applied until the ledger is captured; a pong or a query response
        is parked for nobody once the dial is ending. A captured sink takes nothing.
        Raises :class:`ReplyOutOfOrderError` for an ack or a query response that
        matches nothing owed.
        """
        with self._cond:
            if self._captured:
                return
            if isinstance(msg, AckMessage):
                self._deliver_ack(msg)
            elif self._end.closing is not None:
                return
            elif isinstance(msg, PongMessage):
                self._waiters.deliver_pong_locked(msg)
            elif isinstance(msg, QueryResponse):
                self._waiters.deliver_query_locked(msg)
            self._cond.notify_all()

    def end(self, cause: RetireCause) -> bool:
        """Record who ended the dial, and fail every waiter; whether this call did.

        The first cause stands. The ledger is untouched and an ack still applies, so
        the dial's reader can read what the display sent before the ledger is taken.
        """
        with self._cond:
            if not self._end.record(cause):
                return False
            self._waiters.fail_all_locked()
            return True

    def end_by_writer(self, cause: RetireCause) -> bool:
        """Record ``cause`` for a failed write, unless the dial is already ending.

        One step under the sink's lock: nothing is recorded when a cause stands or the
        Hub has asked, and waiters fail when it records. Whether this call recorded.
        """
        with self._cond:
            if not self._end.record_unless_closing(cause):
                return False
            self._waiters.fail_all_locked()
            return True

    def request_hub(self) -> bool:
        """Ask for the Hub's end: refuse writes and fail every waiter; no cause.

        Whether this call asked first. No cause is recorded: a display that died
        first is the display's end, which only :meth:`decide` can tell.
        """
        with self._cond:
            if not self._end.ask_hub():
                return False
            self._waiters.fail_all_locked()
            return True

    def decide(self, *, saw_end: bool) -> RetireCause:
        """Fix the cause, first recorded wins; the one that stands.
        See :meth:`DialEnd.decide <punt_lux.domain.hub.dial_end.DialEnd.decide>`: the
        end of file the reader saw is the display's, else a Hub request is the Hub's,
        else the cause recorded stands.
        """
        with self._cond:
            fresh = self._end.cause is None
            cause = self._end.decide(saw_end=saw_end)
            if fresh:
                self._waiters.fail_all_locked()
            return cause

    def capture(self) -> Settlement:
        """Take the ledger: the scenes still owed, in write order, once.

        Only a dial whose cause is decided is captured. A second capture returns what
        is left, which is nothing. A reply already handed over stays for its waiter to
        take: it arrived before the end.
        """
        with self._cond:
            if self._end.cause is None:
                msg = "a sink that has not ended has no ledger to capture"
                raise ValueError(msg)
            owed = tuple(self._acks)
            self._acks.clear()
            self._captured = True
            self._cond.notify_all()
            return Settlement(owed, self._acked, self._end.cause)

    def _deliver_ack(self, ack: AckMessage) -> None:
        if not self._acks:
            msg = f"ack for {ack.scene_id!r} arrived when none was owed"
            raise ReplyOutOfOrderError(msg)
        owed = self._acks[0]
        if owed != ack.scene_id:
            # The head stays: a skew must not destroy the record of what was owed.
            msg = f"ack for {ack.scene_id!r} arrived where {owed!r} was owed"
            raise ReplyOutOfOrderError(msg)
        self._acks.popleft()
        self._acked = True
        if not self._acks:
            self._waiters.ledger_emptied_locked(ack)
