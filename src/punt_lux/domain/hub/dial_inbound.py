"""DialInbound -- what one dial's socket says: the bytes read from it, and its frames.

A dial's frame buffer is fed from one place. A read waits for the display to speak, or
takes only what is already there (the drain, which never waits). Both hold the dial's
socket lock across the ``recv``, because a TLS socket forbids a read and a write at
once, and both take what TLS has already decrypted but ``select`` cannot see.
"""

from __future__ import annotations

import select
import socket
import ssl
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.protocol import FrameReader
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterator

    from punt_lux.protocol import Message

__all__ = ["DialInbound"]

_READ_CHUNK = 65536


@final
class DialInbound:
    """Read one socket, and turn what it says into messages."""

    _sock: socket.socket
    _lock: threading.Lock
    _endpoint: str
    _frames: FrameReader
    __slots__ = ("_endpoint", "_frames", "_lock", "_sock")

    def __new__(cls, sock: socket.socket, lock: threading.Lock, endpoint: str) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._lock = lock
        self._endpoint = endpoint
        self._frames = FrameReader()
        return self

    def poll(self, timeout: float, require_open: Callable[[], None]) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` is the one normal non-answer: nothing arrived in time. A display that
        closed the stream raises :class:`ConnectionClosedError`; ``require_open`` is
        asked again under the socket lock, so a read never starts on a retired dial.
        """
        readable, _, _ = select.select([self._sock], [], [], timeout)
        if not readable:
            return None
        with self._lock:
            require_open()
            chunk = self._sock.recv(_READ_CHUNK)
            chunk += self._decrypted_backlog()
        if not chunk:
            msg = f"the display at {self._endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return chunk

    def drain(self) -> bytes | None:
        """Take what the socket already holds, without waiting; ``None`` if nothing.

        A stream that has ended or failed holds nothing more, so it too is ``None``:
        the drain is a last look, and what the display sent first is all it wants.
        """
        try:
            readable, _, _ = select.select([self._sock], [], [], 0)
            if not readable:
                return None
            with self._lock:
                chunk = self._sock.recv(_READ_CHUNK) + self._decrypted_backlog()
        except (OSError, ValueError):
            return None
        return chunk or None

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

    def _decrypted_backlog(self) -> bytes:
        """What TLS already decrypted but ``select`` cannot see, so it is not stranded.

        ``select`` watches the file descriptor; a record batch read in one ``recv``
        can leave plaintext in the SSL buffer with the descriptor quiet. Called
        under the socket lock, straight after the ``recv``.
        """
        sock = self._sock
        if not isinstance(sock, ssl.SSLSocket):
            return b""
        backlog = b""
        while waiting := sock.pending():
            backlog += sock.recv(waiting)
        return backlog
