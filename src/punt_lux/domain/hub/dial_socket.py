"""DialSocket -- one dial's socket: what it says, and every write.

A dial's socket is read by one reader at a time and written by one writer at a time;
who reads is the connection's decision (the
:class:`~punt_lux.domain.hub.reader_slot.ReaderSlot` it publishes with the dial), and
this object's I/O does not consult it. Both hold the socket's lock across the
``recv`` or the ``sendall``, because a TLS socket forbids a read and a write at once;
a write also holds it across the bookkeeping that goes with it (the ack a scene is
owed, the reply a ping or query waits for), so the reader cannot take a byte of a
reply before its entry exists.

A read waits for the display to speak, or takes only what is already there (the drain,
which never waits), and both take what TLS already decrypted but ``select`` cannot see.
A write that raises may have left half a frame on the wire, so it reports to the dial,
which ends it; the dial, not this object, decides who ended it and whether the failure
is the display's.
"""

from __future__ import annotations

import contextlib
import logging
import select
import socket
import ssl
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.protocol import FrameReader, PingMessage, encode_message
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.reply_sink import Pending, ReplySink
    from punt_lux.protocol import (
        Message,
        PongMessage,
        QueryRequest,
        QueryResponse,
        ReadyMessage,
        SceneMessage,
    )

logger = logging.getLogger(__name__)

__all__ = ["DialSocket"]

_READ_CHUNK = 65536


@final
class DialSocket:
    """Read and write one socket, under its lock, one at a time."""

    _dial: HandshakeResult
    _lock: threading.Lock
    _sink: ReplySink
    _frames: FrameReader
    _require_open: Callable[[], None]
    _failed: Callable[[BaseException], None]
    __slots__ = (
        "_dial",
        "_failed",
        "_frames",
        "_lock",
        "_require_open",
        "_sink",
    )

    def __new__(
        cls,
        dial: HandshakeResult,
        sink: ReplySink,
        *,
        require_open: Callable[[], None],
        failed: Callable[[BaseException], None],
    ) -> Self:
        self = super().__new__(cls)
        self._dial = dial
        self._lock = threading.Lock()
        self._sink = sink
        self._frames = FrameReader()
        self._require_open = require_open
        self._failed = failed
        return self

    @property
    def endpoint(self) -> str:
        """The label of the display this dial reached, for logs only."""
        return self._dial.endpoint

    @property
    def ready(self) -> ReadyMessage:
        """The ``ReadyMessage`` the handshake received."""
        return self._dial.ready

    def send(self, msg: Message) -> None:
        """Write ``msg``, serialized against every other writer."""
        wire = encode_message(msg)
        self._write_locked(lambda: None, lambda _: self._dial.sock.sendall(wire))

    def send_scene(self, msg: SceneMessage) -> None:
        """Write a scene and record the ack it is owed, in wire order.

        The ledger entry is made under the socket lock, after the write returned:
        the reader cannot take a byte before the lock is released, so the ack can
        never be read before its entry exists, and a write that raised owes none.
        """
        wire = encode_message(msg)

        def write_then_owe(_: None) -> None:
            self._dial.sock.sendall(wire)
            self._sink.owe_ack(msg.id)

        self._write_locked(lambda: None, write_then_owe)

    def send_ping(self, ts: float) -> Pending[float, PongMessage]:
        """Register the ping in flight, then write it; one step under the lock."""
        wire = encode_message(PingMessage(ts=ts))

        def write(pending: Pending[float, PongMessage]) -> Pending[float, PongMessage]:
            self._dial.sock.sendall(wire)
            return pending

        return self._write_locked(lambda: self._sink.expect_pong(ts), write)

    def send_query(self, request: QueryRequest) -> Pending[None, QueryResponse]:
        """Register the query in flight, then write it; one step under the lock."""
        wire = encode_message(request)

        def write(
            pending: Pending[None, QueryResponse],
        ) -> Pending[None, QueryResponse]:
            self._dial.sock.sendall(wire)
            return pending

        return self._write_locked(self._sink.expect_query, write)

    def poll(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display that
        closed the stream raises :class:`ConnectionClosedError`; the dial is asked
        again under the socket lock, so a read never starts on an ended dial.
        """
        readable, _, _ = select.select([self._dial.sock], [], [], timeout)
        if not readable:
            return None
        with self._lock:
            self._require_open()
            chunk = self._dial.sock.recv(_READ_CHUNK)
            chunk += self._decrypted_backlog()
        if not chunk:
            msg = f"the display at {self.endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return chunk

    def drain(self) -> bytes | None:
        """Take what the socket already holds, without waiting; ``None`` if nothing.

        A stream that has ended or failed holds nothing more, so it too is ``None``:
        the drain is a last look, and what the display sent first is all it wants.
        """
        try:
            readable, _, _ = select.select([self._dial.sock], [], [], 0)
            if not readable:
                return None
            with self._lock:
                chunk = self._dial.sock.recv(_READ_CHUNK) + self._decrypted_backlog()
        except (OSError, ValueError) as exc:
            self._report_cut_short(exc)
            return None
        return chunk or None

    def _report_cut_short(self, exc: BaseException) -> None:
        """Say the last look was cut short: the capture goes ahead on what it read.

        Quietly when the stream simply ended (a reset, a broken pipe, TLS end of
        file), loudly for anything else (a closed descriptor, a TLS fault): a later
        look at why a surviving scene was charged finds the trace.
        """
        ended = isinstance(exc, ConnectionError | ssl.SSLEOFError)
        logger.log(
            logging.DEBUG if ended else logging.WARNING,
            "Drain of %s cut short: %r",
            self._dial.endpoint,
            exc,
        )

    def messages(self, chunk: bytes) -> Iterator[Message]:
        """Feed ``chunk`` to the frame buffer; yield each message it completes.

        A frame of a kind a display never sends raises ``ValueError`` before it is
        decoded; any decoder failure propagates, and ends the stream.
        """
        self._frames.feed(chunk)
        return self._frames.iter_typed(DISPLAY_VOCABULARY)

    def head(self, count: int) -> bytes:
        """The first ``count`` unread bytes, for a log line about a bad frame."""
        return self._frames.head(count)

    def close(self) -> None:
        """Wake whoever is blocked on the socket, then release it; never raises.

        ``shutdown`` first, so a reader blocked in ``recv`` and a writer wedged in
        ``sendall`` are both woken; then ``close``. On a TLS socket ``shutdown`` is the
        raw socket's, never ``unwrap``, which blocks on a wedged peer.
        """
        with contextlib.suppress(OSError):
            self._dial.sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._dial.sock.close()

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
        """Run one write under the socket lock; a failure inside it ends the dial.

        ``prepare`` is the bookkeeping that precedes the first byte (registering the
        reply owed): if it refuses, nothing was written and nothing is ended.
        Anything raised inside ``write`` -- whatever it is, a ``BaseException``
        included -- may have left a partial frame on the wire, so the dial is told,
        after the lock is released.
        """
        writing = False
        try:
            with self._lock:
                self._require_open()
                prepared = prepare()
                writing = True
                return write(prepared)
        except BaseException as exc:
            if writing:
                self._failed(exc)
            raise
