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

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.reply_sink import Pending, ReplySink
from punt_lux.protocol import FrameReader, encode_message
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY
from punt_lux.send_timeout import set_send_timeout
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
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
    # A leaf: held only to read or change ``_reader``, never while taking another
    # lock or doing I/O. ``claim_reader`` waits on it (an inline read's duration),
    # so no caller may hold a lock the request model or the registry shares.
    _slot: threading.Condition
    # Who reads this dial: nobody, its listener thread, or one caller's inline wait.
    _reader: Literal["none", "listener", "inline"]
    # Reports this dial's own breakage to whoever holds the current dial.
    _retire: Callable[[DialGeneration], object]
    _is_closed: bool
    __slots__ = (
        "_dial",
        "_frames",
        "_is_closed",
        "_lock",
        "_reader",
        "_retire",
        "_sink",
        "_slot",
    )

    def __new__(
        cls,
        dial: HandshakeResult,
        retire: Callable[[DialGeneration], object],
        *,
        listening: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        set_send_timeout(dial.sock)  # every dial path: a wedged peer ends a send
        self._dial = dial
        self._retire = retire
        self._lock = threading.Lock()
        self._sink = ReplySink()
        self._frames = FrameReader()
        self._slot = threading.Condition()
        # Born holding the listener slot when asked: nobody else has seen this dial
        # yet, so no inline read can be in flight when the listener claims it.
        self._reader = "listener" if listening else "none"
        self._is_closed = False
        return self

    @property
    def sink(self) -> ReplySink:
        """The replies this dial is owed."""
        return self._sink

    @property
    def socket(self) -> socket.socket:
        """The dialed socket."""
        return self._dial.sock

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
        return self._is_closed

    @property
    def has_reader(self) -> bool:
        """Whether a listener thread reads this dial (it ends with the dial)."""
        return self._reader == "listener"

    def claim_reader(self) -> bool:
        """Take this dial's one reader slot for a listener; ``False`` if it has one.

        Waits out a caller's inline read in flight: a dial has one reader at a
        time, so two threads never feed one frame buffer.
        """
        with self._slot:
            self._slot.wait_for(lambda: self._reader != "inline")
            if self._reader == "listener":
                return False
            self._reader = "listener"
            return True

    def release_reader(self) -> None:
        """Give the listener's slot back: its thread could not be started."""
        with self._slot:
            if self._reader == "listener":
                self._reader = "none"
                self._slot.notify_all()

    @contextlib.contextmanager
    def inline_reading(self) -> Generator[bool]:
        """Hold the reader slot for a caller's inline read; yield whether it was free.

        ``False`` means a listener or another caller is reading: wait on the sink,
        which that reader feeds.
        """
        with self._slot:
            granted = self._reader == "none"
            if granted:
                self._reader = "inline"
        try:
            yield granted
        finally:
            if granted:
                with self._slot:
                    self._reader = "none"
                    self._slot.notify_all()

    def mark_closed(self) -> None:
        """Record that the connection retired this dial (under its state lock)."""
        self._is_closed = True

    @trace
    def send(self, msg: Message) -> None:
        """Write ``msg``, serialized against every other writer.

        A write that raises leaves a stream that cannot be trusted, so this dial
        retires itself before the error reaches the caller.
        """
        wire = encode_message(msg)
        try:
            with self._lock:
                self._require_open()
                self._dial.sock.sendall(wire)
        except BaseException:
            self._retire(self)
            raise

    @trace
    def send_scene(self, msg: SceneMessage, *, awaited: bool) -> Pending:
        """Write a scene and record the ack it is owed, in wire order.

        The ledger entry is made under the socket lock, after the write returned:
        the reader cannot take a byte before the lock is released, so the ack can
        never be read before its entry exists, and a write that raised owes none.
        """
        wire = encode_message(msg)
        try:
            with self._lock:
                self._require_open()
                self._dial.sock.sendall(wire)
                return self._sink.owe_ack(msg.id, awaited=awaited)
        except BaseException:
            self._retire(self)
            raise

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
            if self._is_closed:  # the fd went away under the wait: our own retirement
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
        self._is_closed = True
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

    def _require_open(self) -> None:
        if self._is_closed:
            raise self._closed_error()

    def _closed_error(self) -> ConnectionClosedError:
        return ConnectionClosedError(f"the connection to {self.endpoint} was closed")
