"""DisplayConnection -- the socket to the display, and every write onto it.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): opening the connection (via a dialer), holding its socket and
``ReadyMessage``, closing it, and serializing writes and the listener's reads
through one lock are one concern. The link's typed calls and the listener
thread are clients of it and share no socket state of their own.
"""

from __future__ import annotations

import contextlib
import select
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.protocol import encode_message, recv_message
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY
from punt_lux.tracing import trace

if TYPE_CHECKING:
    import socket

    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.protocol import Message, ReadyMessage

__all__ = ["DisplayConnection"]

_READ_CHUNK = 65536


@final
class DisplayConnection:
    """One display socket: dialed on open, written and read under a single lock."""

    _dialer: DisplayDialer
    _connect_timeout: float
    # None = not connected; the socket, its endpoint and its ready message are one
    # handshake's result and come and go together.
    _open: HandshakeResult | None
    _lock: threading.Lock
    __slots__ = ("_connect_timeout", "_dialer", "_lock", "_open")

    def __new__(cls, dialer: DisplayDialer, connect_timeout: float) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._open = None
        self._lock = threading.Lock()
        return self

    @property
    def is_open(self) -> bool:
        """Whether a socket is currently held."""
        return self._open is not None

    @property
    def ready(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` the handshake received, or ``None`` if not open."""
        held = self._open
        return None if held is None else held.ready

    @property
    def endpoint(self) -> str:
        """The label of the display this is open to, for logs only.

        ``"not connected"`` is a placeholder for a closed connection, never a
        value to compare or parse.
        """
        held = self._open
        return "not connected" if held is None else held.endpoint

    def open(self) -> None:
        """Dial the display and complete the handshake; a no-op if already open.

        Raises :class:`DisplayNotConnectedError` if the display cannot be
        reached or the handshake fails.
        """
        if self._open is not None:
            return
        self._open = self._dialer.dial(self._connect_timeout)

    def close(self) -> None:
        """Close the socket, if open."""
        held = self._open
        if held is not None:
            with contextlib.suppress(OSError):
                held.sock.close()
            self._open = None

    def require(self) -> socket.socket:
        """Return the open socket, or raise if the connection is not open."""
        held = self._open
        if held is None:
            msg = "Not connected — open() the display connection first"
            raise ConnectionClosedError(msg)
        return held.sock

    def receive(self, timeout: float) -> Message | None:
        """Read one message the display may send, or ``None`` after ``timeout``.

        A frame of any kind a display never sends raises ``ValueError`` before it
        is decoded.
        """
        return recv_message(self.require(), DISPLAY_VOCABULARY, timeout=timeout)

    @trace
    def send(self, msg: Message) -> None:
        """Write ``msg`` to the open socket, serialized against other writers."""
        sock = self.require()
        wire = encode_message(msg)
        with self._lock:
            sock.sendall(wire)

    def poll_chunk(self, timeout: float) -> bytes | None:
        """Wait up to ``timeout`` for the display to say something, and read it.

        ``None`` means nothing arrived in time -- the one normal non-answer, so
        an optional return is its honest type. A display that closed the
        connection raises :class:`ConnectionClosedError`, as does a connection
        that is not open; ``OSError`` or ``ValueError`` propagate when the socket
        fails or is closed under the wait, for the listener to report. The socket
        never leaves the connection: the wait and the read both happen here, the
        read serialized against writers.
        """
        sock = self.require()
        readable, _, _ = select.select([sock], [], [], timeout)
        if not readable:
            return None  # a timeout, not an end: the caller waits again
        with self._lock:
            chunk = sock.recv(_READ_CHUNK)
        if not chunk:
            msg = f"the display at {self.endpoint} closed the connection"
            raise ConnectionClosedError(msg)
        return chunk
