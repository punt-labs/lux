"""DialSocket -- one dial's socket: what it says, and every write.

A dial's socket is read by one reader at a time and written by one writer at a time;
who reads is the connection's decision (the
:class:`~punt_lux.domain.hub.reader_slot.ReaderSlot` it publishes with the dial), and
this object's I/O does not consult it. Both hold the socket's lock across the
``recv`` or the bounded send, because a TLS socket forbids a read and a write at once;
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

from punt_lux.bounded_send import BoundedSend, ProgressClock
from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.drain_result import CutShort, Drained, DrainIncompleteError
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
    _progress: ProgressClock
    _require_open: Callable[[], None]
    _failed: Callable[[BaseException], None]
    __slots__ = (
        "_dial",
        "_failed",
        "_frames",
        "_lock",
        "_progress",
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
        self._progress = ProgressClock()
        self._require_open = require_open
        self._failed = failed
        return self

    def is_progressing(self) -> bool:
        """Whether a byte moved on this socket within ``D``: the dial is live.

        The one clock the writer's deadline, a lock wait and the keepalive all read, so
        none of them judges a dial that is moving bytes unresponsive.
        """
        return self._progress.progressed_within(SCENE_WRITE_DEADLINE_SECONDS)

    @property
    def endpoint(self) -> str:
        """The label of the display this dial reached, for logs only."""
        return self._dial.endpoint

    @property
    def ready(self) -> ReadyMessage:
        """The ``ReadyMessage`` the handshake received."""
        return self._dial.ready

    @property
    def is_tls(self) -> bool:
        """Whether this dial's socket is TLS: the cross-host transport."""
        return isinstance(self._dial.sock, ssl.SSLSocket)

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
        # Checked before anything is waited for: a poll made under the store lock
        # fails the first time it runs, on a quiet socket as on a busy one.
        LockDiscipline.forbid_store("the dial socket lock")
        readable, _, _ = select.select([self._dial.sock], [], [], timeout)
        if not readable:
            return None
        with self._lock:
            self._require_open()
            look = self._read_now()
        if look.ended:
            msg = f"the display at {self.endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return look.chunk or None  # readable, but no application byte yet: nothing

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
        LockDiscipline.forbid_store("the dial socket lock")  # on every drain, first
        try:
            readable, _, _ = select.select([self._dial.sock], [], [], 0)
            if not readable:
                return Drained(b"", ended=False)
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
                return self._read_now()
            finally:
                self._lock.release()
        except (OSError, ValueError) as exc:
            CutShort(
                self.endpoint, exc, captured=self._sink.captured, is_tls=self.is_tls
            ).report()
            return Drained(b"", ended=True)

    def _read_now(self) -> Drained:
        """Read what the socket holds without waiting, on either transport.

        The lock is held. The socket is made non-blocking for this read alone: a TLS
        socket's descriptor is readable for post-handshake records (session tickets)
        that carry no application byte, and a blocking ``recv`` would wait for one.
        Three answers, none packed into another: bytes, the stream's end, and nothing
        more now (no bytes, not ended).
        """
        sock = self._dial.sock
        sock.settimeout(0.0)
        try:
            chunk = sock.recv(_READ_CHUNK) + self._decrypted_backlog()
            if chunk:
                self._progress.moved()  # application data came: the display is moving
            return Drained(chunk, ended=not chunk)
        except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
            # Nothing now. A TLS read may need to write (a key update) into a send
            # buffer a stalled peer has filled: that is the write's deadline to judge,
            # not an end of the display's.
            return Drained(b"", ended=False)
        finally:
            with contextlib.suppress(OSError):  # closed by its own capture meanwhile
                sock.settimeout(None)

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
        and :class:`BoundedSend` waits for it. The bound is ``D`` of *no progress*, not
        ``D`` of elapsed time: every byte that moves on the socket, the write's own
        included, restarts it, for the wait for the lock as for the write. A write that
        keeps moving bytes is never cut short; one that has moved none for ``D``, or a
        lock still held with no byte moving for ``D``, ends the dial as unresponsive.
        The socket lock is held, so nothing reads meanwhile.
        """
        LockDiscipline.forbid_store("the dial socket lock")
        if not self._progress.acquire(self._lock, SCENE_WRITE_DEADLINE_SECONDS):
            stalled = BlockingIOError("the dial's socket lock was not free in time")
            self._failed(stalled)
            raise stalled
        self._progress.moved()  # a writer that has the lock starts its own window
        writing = False
        try:
            try:
                self._require_open()
                prepared = prepare()
                writing = True
                sock = self._dial.sock
                sock.settimeout(0.0)
                try:
                    BoundedSend().send_while_progressing(
                        sock, wire, self._progress, SCENE_WRITE_DEADLINE_SECONDS
                    )
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
