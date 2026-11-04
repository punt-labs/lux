"""DialSocket -- one dial's socket: what the display says, and the line to it.

A dial's socket is read by one reader at a time and written by one writer at a time;
who reads is the connection's decision (the
:class:`~punt_lux.domain.hub.reader_slot.ReaderSlot` it publishes with the dial), and
this object's I/O does not consult it. A read takes the socket's line, the lock a write
takes too, because a TLS socket forbids a read and a write at once; the writer that
shares the line is lent by :meth:`DialSocket.writer`.

A read waits for the display to speak, or takes only what is already there (the drain,
which never waits), and both take what TLS already decrypted but ``select`` cannot see.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import ssl
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_writer import DialWriter
from punt_lux.domain.hub.drain_result import CutShort, Drained, DrainIncompleteError
from punt_lux.domain.hub.socket_line import SocketLine
from punt_lux.protocol import FrameReader
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY
from punt_lux.send_timeout import SEND_TIMEOUT_CEILING_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.domain.hub.reply_sink import ReplySink
    from punt_lux.protocol import Message, ReadyMessage

logger = logging.getLogger(__name__)

__all__ = ["DialSocket"]

_READ_CHUNK = 65536


@final
class DialSocket:
    """Read one socket, under its line, and lend the writer that shares the line."""

    _dial: HandshakeResult
    _line: SocketLine
    _sink: ReplySink
    _frames: FrameReader
    _require_open: Callable[[], None]
    __slots__ = ("_dial", "_frames", "_line", "_require_open", "_sink")

    def __new__(
        cls,
        dial: HandshakeResult,
        sink: ReplySink,
        *,
        require_open: Callable[[], None],
    ) -> Self:
        self = super().__new__(cls)
        self._dial = dial
        self._line = SocketLine()
        self._sink = sink
        self._frames = FrameReader()
        self._require_open = require_open
        return self

    def writer(self, failed: Callable[[BaseException], None]) -> DialWriter:
        """The writer to this socket: it takes the same line a read does.

        ``failed`` is told of a write that raised from its first byte on, which may
        have left half a frame on the wire.
        """
        return DialWriter(
            self._dial.sock,
            self._line,
            require_open=self._require_open,
            failed=failed,
        )

    def is_progressing(self) -> bool:
        """Whether a byte moved on this socket within ``D``: the dial is live.

        The one clock the writer's deadline, a lock wait and the keepalive all read, so
        none of them judges a dial that is moving bytes unresponsive.
        """
        return self._line.is_progressing()

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

    def poll(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display that
        closed the stream raises :class:`ConnectionClosedError`; the dial is asked
        again under the socket lock, so a read never starts on an ended dial.
        """
        # The line refuses a poll made under the store lock before anything is
        # waited for: it fails the first time it runs, on a quiet socket as on a busy
        # one.
        if not self._line.readable(self._dial.sock, timeout):
            return None
        with self._line.reading():
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
        try:
            if not self._line.readable(self._dial.sock, 0):
                return Drained.quiet()
            with self._line.draining(SEND_TIMEOUT_CEILING_SECONDS) as free:
                if free:
                    return self._read_now()
            # A writer holds the lock past the send timeout. Bytes are readable and
            # unread, so this is no answer: the look is incomplete, and the settle
            # leaves the capture to the bound.
            logger.warning(
                "Drain of %s incomplete: a writer held the socket past %ss",
                self.endpoint,
                SEND_TIMEOUT_CEILING_SECONDS,
            )
            msg = f"the last look at {self.endpoint} could not be made"
            raise DrainIncompleteError(msg)
        except (OSError, ValueError) as exc:
            CutShort(
                self.endpoint, exc, captured=self._sink.captured, is_tls=self.is_tls
            ).report()
            return Drained.end()

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
                self._line.moved()
            return Drained.holding(chunk) if chunk else Drained.end()
        except (BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
            # Nothing now. A TLS read may need to write (a key update) into a send
            # buffer a stalled peer has filled: that is the write's deadline to judge,
            # not an end of the display's.
            return Drained.quiet()
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

        ``shutdown`` first, so a reader blocked in ``recv`` and a writer blocked in a
        send are both woken; then ``close``. On a TLS socket ``shutdown`` is the
        raw socket's, never ``unwrap``, which blocks on a peer that has stopped
        reading.
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
