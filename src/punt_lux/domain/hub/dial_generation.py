"""DialGeneration -- one dial's socket, and everything that belongs to it alone.

A dial makes a generation; nothing of an earlier one is carried over. It owns the
socket, the bytes read from it, the sink of replies it is owed, and the one reader
that may run on it. Whoever holds a generation reads and writes *its* socket and
settles *its* sink, so a thread that outlives a redial can never touch the new
dial's bytes or waiters. (This is a per-dial object, not the reconnect counter
the hub's client registry keeps for waiters of a reconnect.)

Lock order: the socket lock ``_lock`` is held across one write (and the ack ledger
entry the write makes, which takes the sink's lock, the leaf) or across one
``recv``. A report, a retirement and ``shut`` take neither: shutdown is what
releases a sender wedged in ``sendall`` while it holds ``_lock``. The sink's lock
is never held while taking ``_lock``.

Every dial's socket carries the send timeout (``SO_SNDTIMEO``), set here whichever
dialer made it: a peer that stops reading wedges a writer in ``sendall`` while it
holds ``_lock``, and the timeout is what ends that write. A send that raises
retires the dial, which fails every writer queued behind it.
"""

from __future__ import annotations

import contextlib
import select
import socket
import ssl
import threading
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.reader_slot import ReaderSlot
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.protocol import (
    AckMessage,
    FrameReader,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    encode_message,
)
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY
from punt_lux.send_timeout import set_send_timeout
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.reply_sink import Pending
    from punt_lux.protocol import Message, ReadyMessage, SceneMessage

__all__ = ["DialGeneration"]

_READ_CHUNK = 65536


@final
class DialGeneration:
    """One dialed socket, its replies owed, and at most one reader."""

    _dial: HandshakeResult
    _lock: threading.Lock
    _sink: ReplySink
    _frames: FrameReader
    # Who reads this dial: nobody, its listener thread, or one caller's inline wait.
    _slot: ReaderSlot
    # Reports this dial's own breakage to whoever holds the current dial.
    _retire: Callable[[DialGeneration, RetireCause], object]
    # None while open; once retired, who ended it (first retirement wins).
    _ended: RetireCause | None
    # Whether a death this dial's end evidences has been charged to a sender yet.
    _is_blamed: bool
    __slots__ = (
        "_dial",
        "_ended",
        "_frames",
        "_is_blamed",
        "_lock",
        "_retire",
        "_sink",
        "_slot",
    )

    def __new__(
        cls,
        dial: HandshakeResult,
        retire: Callable[[DialGeneration, RetireCause], object],
        *,
        reader: Literal["none", "listener"] = "none",
    ) -> Self:
        self = super().__new__(cls)
        set_send_timeout(dial.sock)  # every dial path: a wedged peer ends a send
        self._dial = dial
        self._retire = retire
        self._lock = threading.Lock()
        self._sink = ReplySink()
        self._frames = FrameReader()
        # Born holding the listener slot when asked: nobody else has seen this dial
        # yet, so no inline read can be in flight when the listener claims it.
        self._slot = ReaderSlot(reader)
        self._ended = None
        self._is_blamed = False
        return self

    @property
    def owed_acks(self) -> int:
        """How many acks the display still owes this dial: the bound on its sink."""
        return self._sink.owed_acks

    @property
    def endpoint(self) -> str:
        """The label of the display this dial reached, for logs only."""
        return self._dial.endpoint

    @property
    def ready(self) -> ReadyMessage:
        """The ``ReadyMessage`` the handshake received."""
        return self._dial.ready

    @property
    def is_closed(self) -> bool:
        """Whether this dial has been retired."""
        return self._ended is not None

    @property
    def ended_by(self) -> RetireCause | None:
        """Who retired this dial, or ``None`` while it is open."""
        return self._ended

    @property
    def is_blamed(self) -> bool:
        """Whether this dial's end has already been charged to a sender."""
        return self._is_blamed

    def claim_blame(self) -> bool:
        """Charge this dial's end to a sender; ``False`` if it was already charged.

        Called by the one worker that attributes deaths, so a death the display
        caused is counted once however many sends find the dial gone.
        """
        claimed = not self._is_blamed
        self._is_blamed = True
        return claimed

    @property
    def has_reader(self) -> bool:
        """Whether a listener thread reads this dial (it ends with the dial)."""
        return self._slot.has_listener

    def claim_reader(self) -> bool:
        """Take this dial's one reader slot for a listener; ``False`` if it has one."""
        return self._slot.claim_for_listener()

    def release_reader(self) -> None:
        """Give the listener's slot back: its thread could not be started."""
        self._slot.release_listener()

    def inline_reading(self) -> AbstractContextManager[bool]:
        """Hold the reader slot for an inline read; yield whether it was free."""
        return self._slot.inline()

    def mark_closed(self, cause: RetireCause) -> None:
        """Retire this dial: record who ended it and refuse every later delivery.

        Called under the connection's state lock, so it takes no I/O: the sink
        is discarded here, and from then on nothing the dial read is delivered
        to anyone. Releasing the socket is :meth:`shut`'s job, outside the lock.
        """
        if self._ended is None:
            self._ended = cause
        self._sink.discard()

    @trace
    def send(self, msg: Message) -> None:
        """Write ``msg``, serialized against every other writer.

        A write that raises leaves a stream that cannot be trusted, so this dial
        retires itself before the error reaches the caller.
        """
        wire = encode_message(msg)
        self._write_locked(lambda: None, lambda _: self._dial.sock.sendall(wire))

    @trace
    def send_scene(
        self, msg: SceneMessage, *, awaited: bool
    ) -> Pending[str, AckMessage]:
        """Write a scene and record the ack it is owed, in wire order.

        The ledger entry is made under the socket lock, after the write returned:
        the reader cannot take a byte before the lock is released, so the ack can
        never be read before its entry exists, and a write that raised owes none.
        """
        wire = encode_message(msg)

        def write_then_owe(_: None) -> Pending[str, AckMessage]:
            self._dial.sock.sendall(wire)
            return self._sink.owe_ack(msg.id, awaited=awaited)

        return self._write_locked(lambda: None, write_then_owe)

    @trace
    def send_ping(self, ts: float) -> Pending[float, PongMessage]:
        """Register the ping in flight, then write it; one step under the lock."""
        wire = encode_message(PingMessage(ts=ts))

        def write(pending: Pending[float, PongMessage]) -> Pending[float, PongMessage]:
            self._dial.sock.sendall(wire)
            return pending

        return self._write_locked(lambda: self._sink.expect_pong(ts), write)

    @trace
    def send_query(self, request: QueryRequest) -> Pending[None, QueryResponse]:
        """Register the query in flight, then write it; one step under the lock."""
        wire = encode_message(request)

        def write(
            pending: Pending[None, QueryResponse],
        ) -> Pending[None, QueryResponse]:
            self._dial.sock.sendall(wire)
            return pending

        return self._write_locked(self._sink.expect_query, write)

    def await_reply[R: Message](
        self, pending: Pending[object, R], timeout: float
    ) -> R | None:
        """Wait up to ``timeout`` for ``pending``'s reply; ``None`` on time.

        Raises the error this dial's retirement reports, the moment it retires.
        """
        try:
            return self._sink.await_reply(pending, timeout)
        except ConnectionClosedError as exc:
            raise self._closed_error() from exc

    def answered(self, pending: Pending[object, Message]) -> bool:
        """Whether ``pending``'s reply has arrived and is waiting to be taken."""
        return self._sink.answered(pending)

    def abandon(self, pending: Pending[object, Message]) -> None:
        """Stop waiting for ``pending``: a late reply is dropped, never kept."""
        self._sink.abandon(pending)

    def deliver(self, msg: Message) -> None:
        """Hand a reply read from this dial to the request it answers.

        Raises :class:`~punt_lux.domain.hub.reply_sink.ReplyOutOfOrderError` for
        one that matches nothing owed; a retired dial delivers nothing.
        """
        self._sink.deliver(msg)

    def poll_chunk(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display
        that closed the stream, or a dial retired under the wait, raises
        :class:`ConnectionClosedError`; any other socket failure propagates.
        """
        self._require_open()
        try:
            readable, _, _ = select.select([self._dial.sock], [], [], timeout)
            if not readable:
                return None
            with self._lock:
                self._require_open()
                chunk = self._dial.sock.recv(_READ_CHUNK)
                chunk += self._decrypted_backlog()
        except (OSError, ValueError) as exc:
            if isinstance(exc, ConnectionClosedError):
                raise
            if self.is_closed:  # the fd went away under the wait: our own retirement
                raise self._closed_error() from exc
            raise
        if not chunk:
            msg = f"the display at {self.endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return chunk

    def messages(self, chunk: bytes) -> Iterator[Message]:
        """Feed chunk to this dial's frame buffer; yield each message it completes.

        A frame of a kind a display never sends raises ``ValueError`` before it is
        decoded; any decoder failure propagates, and ends the stream.
        """
        self._frames.feed(chunk)
        return self._frames.iter_typed(DISPLAY_VOCABULARY)

    def head(self, count: int) -> bytes:
        """The first ``count`` unread bytes, for a log line about a bad frame."""
        return self._frames.head(count)

    def shut(self) -> None:
        """Release the socket and end the sink; idempotent, never under a state lock.

        ``shutdown`` first, so a reader blocked in ``recv`` and a writer wedged in
        ``sendall`` are both woken; then ``close``. On a TLS socket ``shutdown`` is
        the raw socket's, never ``unwrap``, which blocks on a wedged peer.
        """
        if self._ended is None:
            self._ended = "hub"
        with contextlib.suppress(OSError):
            self._dial.sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._dial.sock.close()
        self._sink.discard()

    def _decrypted_backlog(self) -> bytes:
        """What TLS already decrypted but ``select`` cannot see, so it is not stranded.

        ``select`` watches the file descriptor; a record batch read in one ``recv``
        can leave plaintext in the SSL buffer with the descriptor quiet. Called
        under the socket lock, straight after the ``recv``.
        """
        sock = self._dial.sock
        if not isinstance(sock, ssl.SSLSocket):
            return b""
        backlog = b""
        while waiting := sock.pending():
            backlog += sock.recv(waiting)
        return backlog

    def _write_locked[P, R](
        self, prepare: Callable[[], P], write: Callable[[P], R]
    ) -> R:
        """Run one write under the socket lock; a failure inside it retires the dial.

        ``prepare`` is the bookkeeping that precedes the first byte (registering the
        reply owed): if it refuses, nothing was written and nothing is retired.
        Anything raised inside ``write`` -- whatever it is, a ``BaseException``
        included -- may have left a partial frame on the wire, so the dial retires,
        after the lock is released. A socket failure is the display's doing (it reset
        the connection, closed its end, or stopped reading until the send timed out);
        anything else that stopped a write is the Hub's.
        """
        writing = False
        try:
            with self._lock:
                self._require_open()
                prepared = prepare()
                writing = True
                return write(prepared)
        except OSError:
            if writing:
                self._retire(self, "display")
            raise
        except BaseException:
            if writing:
                self._retire(self, "hub")
            raise

    def _require_open(self) -> None:
        if self._ended is not None:
            raise self._closed_error()

    def _closed_error(self) -> ConnectionClosedError:
        """The error that says this dial is gone, and whether the Hub ended it."""
        msg = f"the connection to {self.endpoint} was closed"
        if self._ended == "display":
            return ConnectionClosedError(msg)
        return HubRetiredError(msg)
