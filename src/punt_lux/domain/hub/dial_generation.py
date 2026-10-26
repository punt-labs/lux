"""DialGeneration -- one dial's socket, and everything that belongs to it alone.

A dial makes a generation; nothing of an earlier one is carried over. It owns the
socket (:class:`~punt_lux.domain.hub.dial_socket.DialSocket`: what it says, every
write) and the sink of replies it is owed. Whoever holds a generation reads
and writes *its* socket and settles *its* sink, so a thread that outlives a redial can
never touch the new dial's bytes or waiters.

Lock order: the socket lock is held across one write (and the ack ledger entry the
write makes, which takes the sink's lock, the leaf) or across one ``recv``. An end, a
settlement and ``shut`` take neither: shutdown is what releases a sender wedged in
``sendall`` while it holds the socket lock. The sink's lock is never held while taking
the socket lock. A peer that stops reading cannot wedge a writer for ever: every write
is one user-space bounded send (:class:`~punt_lux.bounded_send.BoundedSend`) on a socket
made non-blocking for it, under one deadline ``D`` that covers the wait for the socket
lock as well (:mod:`punt_lux.send_timeout`). ``SO_SNDTIMEO`` bounds only the
handshake's blocking send, which the dialers set before the dial is handed over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.bounded_send import TornStreamError
from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
    UnresponsiveError,
)
from punt_lux.domain.hub.dial_ref import DialRef
from punt_lux.domain.hub.dial_socket import DialSocket
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.drain_result import Drained
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.pending import Pending
    from punt_lux.domain.hub.settlement import Settlement
    from punt_lux.protocol import (
        AckMessage,
        Message,
        PongMessage,
        QueryRequest,
        QueryResponse,
        ReadyMessage,
        SceneMessage,
    )

__all__ = ["DialEnds", "DialGeneration"]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class DialEnds:
    """How a dial reports its own breakage to whoever holds the current dial.

    ``retire`` ends it for a reason of the Hub's; ``by_writer`` is a failed write's
    report, which records its cause only when nothing is ending the dial already.
    The two callables have one signature, so they are named at every construction.
    """

    retire: Callable[[DialGeneration, RetireCause], bool]
    by_writer: Callable[[DialGeneration, RetireCause], bool]


@final
class DialGeneration:
    """One dialed socket and the replies it is owed."""

    _sink: ReplySink
    _socket: DialSocket
    # The identity every failure names this dial by: one per dial, equal to itself.
    _ref: DialRef
    # Reports this dial's own breakage to whoever holds the current dial.
    _ends: DialEnds
    __slots__ = ("_ends", "_ref", "_sink", "_socket")

    def __new__(
        cls,
        dial: HandshakeResult,
        ends: DialEnds,
    ) -> Self:
        self = super().__new__(cls)
        self._ends = ends
        self._sink = ReplySink()
        self._ref = DialRef(self)
        self._socket = DialSocket(
            dial,
            self._sink,
            require_open=self._require_open,
            failed=self._write_failed,
        )
        return self

    @property
    def owed_acks(self) -> int:
        """How many acks the display still owes this dial: the bound on its sink."""
        return self._sink.owed_acks

    @property
    def endpoint(self) -> str:
        """The label of the display this dial reached, for logs only."""
        return self._socket.endpoint

    def is_progressing(self) -> bool:
        """Whether a byte moved on this dial's socket within ``D``: it is live."""
        return self._socket.is_progressing()

    @property
    def is_cross_host(self) -> bool:
        """Whether this dial reaches a Display on another host: a TLS socket."""
        return self._socket.is_tls

    @property
    def ref(self) -> DialRef:
        """A name for this dial that confers no power over it: what a failure names."""
        return self._ref

    @property
    def ready(self) -> ReadyMessage:
        """The ``ReadyMessage`` the handshake received."""
        return self._socket.ready

    @property
    # PY-TS-14 OK: None while nothing ends the dial: no cause, no Hub request.
    def closing(self) -> RetireCause | None:
        """Who is ending this dial: the cause recorded, else ``hub`` once asked."""
        return self._sink.closing

    @property
    def is_closed(self) -> bool:
        """Whether this dial is being ended: nothing more is written to it.

        True once a cause is recorded and once the Hub has asked to end it.
        """
        return self._sink.closing is not None

    def end(self, cause: RetireCause) -> bool:
        """Record who ended this dial, first cause wins; whether this call did.

        Writes are refused and waiters fail, but the ledger is left alone and an ack
        the display already sent is still applied, so the reader can read it before
        the dial is settled.
        """
        return self._sink.end(cause)

    def end_by_writer(self, cause: RetireCause) -> bool:
        """Record the cause of a failed write unless the dial is already ending.

        The check and the record are one step, so a Hub request landing between a
        write's failure and its record is never overwritten by the write's cause.
        """
        return self._sink.end_by_writer(cause)

    def request_hub(self) -> bool:
        """Ask for the Hub's end of this dial; whether this call asked first.

        Refuses writes and fails waiters at once, like :meth:`end`, but records no
        cause: whether the display is already dead is for the reader that settles the
        dial to find out (:meth:`decide`).
        """
        return self._sink.request_hub()

    def decide(self, *, saw_end: bool) -> RetireCause:
        """Fix the cause of this dial's end: the first recorded, else what was seen.

        ``saw_end`` is the end of the stream a drain found. See
        :meth:`ReplySink.decide <punt_lux.domain.hub.reply_sink.ReplySink.decide>`.
        """
        return self._sink.decide(saw_end=saw_end)

    @property
    # PY-TS-14 OK: None until a cause is recorded or decided: the dial may be open.
    def ended(self) -> RetireCause | None:
        """The first cause recorded for this dial's end; ``None`` while none is."""
        return self._sink.ended

    @property
    def is_settled(self) -> bool:
        """Whether this dial's ledger has been captured: it delivers nothing more."""
        return self._sink.captured

    def await_settled(self, timeout: float) -> bool:
        """Wait up to ``timeout`` for this dial to be settled; whether it was."""
        return self._sink.await_captured(timeout)

    def mark_closed(self, cause: RetireCause) -> Settlement:
        """Capture this dial's ledger, ending it with ``cause`` if nothing had.

        Called under the connection's state lock, so it takes no I/O. The cause that
        stands is the first one recorded. Releasing the socket is :meth:`shut`'s job,
        outside the lock.
        """
        self._sink.end(cause)
        return self._sink.capture()

    @trace
    def send(self, msg: Message) -> None:
        """Write ``msg``, serialized against every other writer.

        A write that raises leaves a stream that cannot be trusted, so this dial
        ends itself before the error reaches the caller.
        """
        self._socket.send(msg)

    @trace
    def send_scene(self, msg: SceneMessage) -> None:
        """Write a scene and record the ack it is owed, in wire order."""
        self._socket.send_scene(msg)

    @trace
    def send_ping(self, ts: float) -> Pending[float, PongMessage]:
        """Register the ping in flight, then write it."""
        return self._socket.send_ping(ts)

    @trace
    def send_query(self, request: QueryRequest) -> Pending[None, QueryResponse]:
        """Register the query in flight, then write it."""
        return self._socket.send_query(request)

    # PY-TS-14 OK: None is the timeout; an end of the dial raises instead.
    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply; ``None`` on time.

        Raises the error this dial's end reports, the moment it ends.
        """
        try:
            return self._sink.await_reply(pending, timeout)
        except ConnectionClosedError as exc:
            raise self.closed_error() from exc

    def answered(self, pending: Pending[object, Message]) -> bool:
        """Whether ``pending``'s reply has arrived and is waiting to be taken."""
        return self._sink.answered(pending)

    # PY-TS-14 OK: None is a ledger already empty: there is nothing to wait for.
    def expect_drained(self) -> Pending[None, AckMessage] | None:
        """Register a wait for every scene written here to be acked; ``None`` if so."""
        return self._sink.expect_drained()

    def abandon(self, pending: Pending[object, Message]) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        self._sink.abandon(pending)

    def deliver(self, msg: Message) -> None:
        """Hand a reply read from this dial to the request it answers.

        Raises ``ReplyOutOfOrderError`` for one that matches nothing owed.
        """
        self._sink.deliver(msg)

    # PY-TS-14 OK: None is the one normal non-answer: nothing arrived in time.
    def poll_chunk(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display that
        closed the stream, or a dial ended under the wait, raises the dial's error.
        """
        self._require_open()
        try:
            return self._socket.poll(timeout)
        except ConnectionClosedError:
            raise
        except (OSError, ValueError) as exc:
            if self.is_closed:  # the fd went away under the wait: our own retirement
                raise self.closed_error() from exc
            raise

    def drain(self) -> Drained:
        """Take what the socket already holds without waiting, and say if it ended."""
        return self._socket.drain()

    def messages(self, chunk: bytes) -> Iterator[Message]:
        """Feed chunk to this dial's frame buffer; yield each message it completes."""
        return self._socket.messages(chunk)

    def head(self, count: int) -> bytes:
        """The first ``count`` unread bytes, for a log line about a bad frame."""
        return self._socket.head(count)

    def shut(self) -> None:
        """Release the socket; idempotent, never under ``st``.

        It records no end at all: a Hub end records nothing, and the ledger is taken by
        :meth:`mark_closed` and by nothing here. ``shutdown`` wakes a reader in ``recv``
        and a writer in ``sendall``; then ``close``. On TLS it is the raw socket's:
        ``unwrap`` blocks on a wedged peer.
        """
        self._socket.close()

    def _write_failed(self, exc: BaseException) -> None:
        """End the dial a failed write left half-written, unless someone already had.

        A socket failure is the display's doing, but a write that hit its deadline
        (``BlockingIOError`` for a frame untouched, ``TornStreamError`` for one half
        written, or a socket lock never free in time) is a display that stopped reading
        and may be alive, so it is recorded as unresponsive. Anything else
        that stopped a write is the Hub's, and is a request, not a recorded cause. A
        dial whose cause is already recorded (``shut`` wakes a writer wedged in
        ``sendall`` on purpose) was ended by whoever's cause it carries: the writer
        reports that cause, never the socket error the ending itself produced. A
        writer that loses the record to one landing after the check reports the
        winner's cause too, and a writer whose own record stands raises its closed
        error as well: the caller dispatches on what ended the dial, not on which
        socket call said so.

        A closed descriptor (``ValueError`` from a socket call after the dial's own
        capture shut it) on a dial that is ending is that race, not a failure of the
        Hub's: it is reported as the dial's closed error too.
        """
        if not isinstance(exc, OSError):
            if isinstance(exc, ValueError) and self._sink.closing is not None:
                raise self.closed_error() from exc
            self._ends.retire(self, "hub")
            return
        cause: RetireCause = (
            "unresponsive"
            if isinstance(exc, BlockingIOError | TornStreamError)
            else "display"
        )
        # A dial already ended, or that the Hub asked to end, records nothing here: the
        # settle decides by what it observes (a queued end of file is the display's).
        self._ends.by_writer(self, cause)
        closing = self._sink.closing
        if closing is not None:  # none is a dial the connection no longer holds
            raise self._error_for(closing, self.endpoint) from exc

    def _require_open(self) -> None:
        if self._sink.closing is not None:
            raise self.closed_error()

    def closed_error(self) -> ConnectionClosedError:
        """The error that says this dial is gone, and who ended it.

        A plain :class:`ConnectionClosedError` when the display ended it,
        :class:`UnresponsiveError` when the Hub gave up on its silence, and
        :class:`HubRetiredError` when the Hub ended it by its own policy (or has asked
        to, with nothing yet decided); only that last changes what recovery does (it
        redials without treating it as a death). ``ValueError`` for a dial still open.
        """
        return self._error_for(self._sink.closing, self.endpoint)

    @staticmethod
    # PY-TS-14 OK: None is a dial nothing has ended or asked to end: still open.
    def _error_for(ended: RetireCause | None, endpoint: str) -> ConnectionClosedError:
        if ended is None:
            msg = f"the connection to {endpoint} is still open"
            raise ValueError(msg)
        msg = f"the connection to {endpoint} was closed"
        if ended == "unresponsive":
            return UnresponsiveError(msg)
        error = ConnectionClosedError if ended == "display" else HubRetiredError
        return error(msg)
