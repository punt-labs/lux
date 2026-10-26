"""DialGeneration -- one dial's socket, and everything that belongs to it alone.

A dial makes a generation; nothing of an earlier one is carried over. It owns the
socket (:class:`~punt_lux.domain.hub.dial_socket.DialSocket`: who reads it, what it
says, every write) and the sink of replies it is owed. Whoever holds a generation reads
and writes *its* socket and settles *its* sink, so a thread that outlives a redial can
never touch the new dial's bytes or waiters.

Lock order: the socket lock is held across one write (and the ack ledger entry the
write makes, which takes the sink's lock, the leaf) or across one ``recv``. An end, a
settlement and ``shut`` take neither: shutdown is what releases a sender wedged in
``sendall`` while it holds the socket lock. The sink's lock is never held while taking
the socket lock. Every socket carries the send timeout (``SO_SNDTIMEO``), set by the
connection that makes it, so a peer that stops reading cannot wedge a writer for ever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
    UnresponsiveError,
)
from punt_lux.domain.hub.dial_socket import DialSocket
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.reply_sink import Pending
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

__all__ = ["DialGeneration"]


@final
class DialGeneration:
    """One dialed socket, its replies owed, and at most one reader."""

    _sink: ReplySink
    _socket: DialSocket
    # Reports this dial's own breakage to whoever holds the current dial.
    _retire: Callable[[DialGeneration, RetireCause], bool]
    __slots__ = ("_retire", "_sink", "_socket")

    def __new__(
        cls,
        dial: HandshakeResult,
        retire: Callable[[DialGeneration, RetireCause], bool],
        *,
        reader: Literal["none", "listener"] = "none",
    ) -> Self:
        self = super().__new__(cls)
        self._retire = retire
        self._sink = ReplySink()
        self._socket = DialSocket(
            dial,
            self._sink,
            reader=reader,
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

    @property
    def ready(self) -> ReadyMessage:
        """The ``ReadyMessage`` the handshake received."""
        return self._socket.ready

    @property
    def is_closed(self) -> bool:
        """Whether this dial has been ended: nothing more is written to it."""
        return self._sink.ended is not None

    @property
    def has_reader(self) -> bool:
        """Whether a listener thread reads this dial (it ends with the dial)."""
        return self._socket.reader_slot.has_listener

    def claim_reader(self) -> bool:
        """Take this dial's one reader slot for a listener; ``False`` if it has one."""
        return self._socket.reader_slot.claim_for_listener()

    def release_reader(self) -> None:
        """Give the listener's slot back: its thread could not be started."""
        self._socket.reader_slot.release_listener()

    def inline_reading(self) -> AbstractContextManager[bool]:
        """Hold the reader slot for an inline read; yield whether it was free."""
        return self._socket.reader_slot.inline()

    def end(self, cause: RetireCause) -> bool:
        """Record who ended this dial, first cause wins; whether this call did.

        Phase one: writes are refused and waiters fail, but the ledger is left alone
        and an ack the display already sent is still applied, so the reader can read
        it before :meth:`mark_closed` takes the ledger.
        """
        return self._sink.end(cause)

    @property
    def ended(self) -> RetireCause | None:
        """Who ended this dial, if anyone has; ``None`` while it is live."""
        return self._sink.ended

    @property
    def is_settled(self) -> bool:
        """Whether this dial's ledger has been captured: it delivers nothing more."""
        return self._sink.captured

    def mark_closed(self, cause: RetireCause) -> Settlement:
        """Settle this dial: end it if no one has, then take its ledger.

        Phase two. Called under the connection's state lock, so it takes no I/O. The
        cause that stands is the first one recorded. Releasing the socket is
        :meth:`shut`'s job, outside the lock.
        """
        return self._sink.discard(cause)

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

    def drain_chunk(self) -> bytes | None:
        """Take what the socket already holds without waiting; ``None`` if nothing."""
        return self._socket.drain()

    def messages(self, chunk: bytes) -> Iterator[Message]:
        """Feed chunk to this dial's frame buffer; yield each message it completes."""
        return self._socket.messages(chunk)

    def head(self, count: int) -> bytes:
        """The first ``count`` unread bytes, for a log line about a bad frame."""
        return self._socket.head(count)

    def shut(self) -> None:
        """Release the socket and fail every waiter; idempotent, never under ``st``.

        It records no more than the end a dial already has: the ledger is taken by
        :meth:`mark_closed` and by nothing here. ``shutdown`` wakes a reader in ``recv``
        and a writer in ``sendall``; then ``close``. On TLS it is the raw socket's:
        ``unwrap`` blocks on a wedged peer.
        """
        self._sink.end("hub")
        self._socket.close()

    def _write_failed(self, exc: BaseException) -> None:
        """End the dial a failed write left half-written, unless someone already had.

        A socket failure is the display's doing; anything else that stopped a write is
        the Hub's. A dial already ended was ended by whoever's cause it carries
        (``shut`` wakes a writer wedged in ``sendall`` on purpose): the writer reports
        that cause, never the socket error the ending itself produced. A writer that
        loses the end to one landing after the check reports the winner's cause too.
        """
        if not isinstance(exc, OSError):
            self._retire(self, "hub")
        elif self._sink.ended is not None or not self._retire(self, "display"):
            raise self.closed_error() from exc  # someone else's cause won the end

    def _require_open(self) -> None:
        if self._sink.ended is not None:
            raise self.closed_error()

    def closed_error(self) -> ConnectionClosedError:
        """The error that says this dial is gone, and who ended it.

        A plain :class:`ConnectionClosedError` when the display ended it and
        :class:`UnresponsiveError` when the Hub gave up on its silence: a sender may
        blame what it was sending. :class:`HubRetiredError` when the Hub ended it by
        its own policy. ``ValueError`` for a dial still open.
        """
        ended = self._sink.ended
        if ended is None:
            msg = f"the connection to {self.endpoint} is still open"
            raise ValueError(msg)
        msg = f"the connection to {self.endpoint} was closed"
        if ended == "unresponsive":
            return UnresponsiveError(msg)
        error = ConnectionClosedError if ended == "display" else HubRetiredError
        return error(msg)
