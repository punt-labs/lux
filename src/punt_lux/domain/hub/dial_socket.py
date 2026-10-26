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
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.bounded_send import BoundedSend
from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.drain_result import Drained, DrainIncompleteError
from punt_lux.domain.hub.lock_discipline import LockDiscipline
from punt_lux.protocol import FrameReader, PingMessage, encode_message
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY
from punt_lux.send_timeout import (
    SCENE_WRITE_DEADLINE_SECONDS,
    SEND_TIMEOUT_CEILING_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.pending import Pending
    from punt_lux.domain.hub.reply_sink import ReplySink
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
        self._write_locked(encode_message(msg), lambda: None, lambda _: None)

    def send_scene(self, msg: SceneMessage) -> None:
        """Write a scene and record the ack it is owed, in wire order.

        The ledger entry is made under the socket lock, after the write returned:
        the reader cannot take a byte before the lock is released, so the ack can
        never be read before its entry exists, and a write that raised owes none.
        """
        self._write_locked(
            encode_message(msg), lambda: None, lambda _: self._sink.owe_ack(msg.id)
        )
        self._require_open()  # owed all the same; the caller learns the dial is ending

    def send_ping(self, ts: float) -> Pending[float, PongMessage]:
        """Register the ping in flight, then write it; one step under the lock."""
        return self._write_locked(
            encode_message(PingMessage(ts=ts)),
            lambda: self._sink.expect_pong(ts),
            lambda pending: pending,
        )

    def send_query(self, request: QueryRequest) -> Pending[None, QueryResponse]:
        """Register the query in flight, then write it; one step under the lock."""
        return self._write_locked(
            encode_message(request), self._sink.expect_query, lambda pending: pending
        )

    def poll(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display that
        closed the stream raises :class:`ConnectionClosedError`; the dial is asked
        again under the socket lock, so a read never starts on an ended dial.
        """
        readable, _, _ = select.select([self._dial.sock], [], [], timeout)
        if not readable:
            return None
        LockDiscipline.forbid_store("the dial socket lock")
        with self._lock:
            self._require_open()
            chunk = self._dial.sock.recv(_READ_CHUNK)
            chunk += self._decrypted_backlog()
        if not chunk:
            msg = f"the display at {self.endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return chunk

    def drain(self) -> Drained:
        """Take what the socket already holds, without waiting; say if its end came.

        Never waits, on either transport: the read is made on the socket in
        non-blocking mode, so a TLS socket whose descriptor is readable for records
        that carry no application byte reports nothing more, not a hang.

        The last look before a dial is settled. The stream's end is what the look
        found: end of file, a connection reset (the peer closed with bytes of this
        side's it never read, which a same-host stream delivers after everything it
        had queued), a TLS end of file, or a read that failed, since a stream that
        cannot be read holds nothing more. A cut-short read is therefore never
        reported as "nothing more": the reader that settles the dial is told it
        found the end, which is what makes a display dead when it looked a display's
        end, not the Hub's. Raises :class:`DrainIncompleteError` when a writer holds
        the socket past the ceiling: with bytes readable, no look at all is no answer.
        """
        try:
            readable, _, _ = select.select([self._dial.sock], [], [], 0)
            if not readable:
                return Drained(b"", ended=False)
            LockDiscipline.forbid_store("the dial socket lock")
            if not self._lock.acquire(timeout=SEND_TIMEOUT_CEILING_SECONDS):
                # A writer holds the lock past the send timeout. Bytes are readable
                # and unread, so this is no answer: the look is incomplete, and the
                # settle leaves the capture to the bound.
                logger.warning(
                    "Drain of %s incomplete: a writer held the socket past %ss",
                    self.endpoint,
                    SEND_TIMEOUT_CEILING_SECONDS,
                )
                msg = f"the last look at {self.endpoint} could not be made"
                raise DrainIncompleteError(msg)
            try:
                sock = self._dial.sock
                sock.settimeout(0.0)  # the look never waits, on either transport
                try:
                    chunk = sock.recv(_READ_CHUNK) + self._decrypted_backlog()
                except (BlockingIOError, ssl.SSLWantReadError):
                    # Readable, but no application byte yet: a TLS socket's
                    # post-handshake records (session tickets) wake ``select`` and
                    # hold nothing. Nothing more now; end of file is a read of b"".
                    return Drained(b"", ended=False)
                finally:
                    with contextlib.suppress(OSError):  # closed by its own capture
                        sock.settimeout(None)
            finally:
                self._lock.release()
        except (OSError, ValueError) as exc:
            self._report_cut_short(exc)
            return Drained(b"", ended=True)
        return Drained(chunk, ended=not chunk)

    def _report_cut_short(self, exc: BaseException) -> None:
        """Say the last look found the stream broken: the settle goes ahead on it.

        Quietly when the stream simply ended (a reset on the same host, a broken
        pipe, TLS end of file) or was closed by the dial's own capture, which this
        look lost the race to. Loudly for a reset from a remote peer, which can
        discard acks queued behind it and so charge a scene that survived, and for
        anything else (a closed descriptor, a TLS fault): a later look at why a
        surviving scene was charged finds the trace.
        """
        if self._sink.captured:
            logger.debug(
                "Drain of %s found the socket closed by its own capture: %r",
                self._dial.endpoint,
                exc,
            )
            return
        remote_reset = isinstance(exc, ConnectionResetError) and isinstance(
            self._dial.sock, ssl.SSLSocket
        )
        ended = isinstance(exc, ConnectionError | ssl.SSLEOFError) and not remote_reset
        if remote_reset:
            logger.warning(
                "Drain of %s cut short by a reset from a remote display, which may "
                "have discarded acks queued behind it: a scene it acked may be "
                "charged: %r",
                self._dial.endpoint,
                exc,
            )
            return
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
        self, wire: bytes, prepare: Callable[[], P], finish: Callable[[P], R]
    ) -> R:
        """Write ``wire`` under the socket lock within one deadline, D; fail the dial.

        ``prepare`` is the bookkeeping that precedes the first byte (registering the
        reply owed): if it refuses, nothing was written and nothing is ended. ``finish``
        is what follows the last byte, under the same lock hold: the ack entry, or the
        ticket handed back. Anything raised from the first byte on, a ``BaseException``
        included, may have left a partial frame on the wire, so the dial is told,
        after the lock is released.

        The same user-space bounded send on either transport, because ``SO_SNDTIMEO``
        does not bound a TLS write: the socket is made non-blocking for the write alone
        and :class:`BoundedSend` waits for it, with one deadline for the whole write,
        the wait for the lock included. A write the deadline cut short, or a lock never
        free in time, ends the dial as unresponsive. The socket lock is held, so
        nothing reads meanwhile.
        """
        LockDiscipline.forbid_store("the dial socket lock")
        deadline = time.monotonic() + SCENE_WRITE_DEADLINE_SECONDS
        if not self._lock.acquire(timeout=max(deadline - time.monotonic(), 0.0)):
            stalled = BlockingIOError("the dial's socket lock was not free in time")
            self._failed(stalled)
            raise stalled
        writing = False
        try:
            try:
                self._require_open()
                prepared = prepare()
                writing = True
                sock = self._dial.sock
                sock.settimeout(0.0)
                try:
                    BoundedSend().send(sock, wire, deadline)
                finally:
                    with contextlib.suppress(OSError):  # closed by its own capture
                        sock.settimeout(None)
                return finish(prepared)
            finally:
                self._lock.release()
        except BaseException as exc:
            if writing:
                self._failed(exc)
            raise
