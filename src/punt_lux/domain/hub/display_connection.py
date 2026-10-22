"""DisplayConnection -- the socket to the display, and every write onto it.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): opening the connection (via a dialer), holding its socket and
``ReadyMessage``, closing it, and serializing writes and the listener's reads
through one lock are one concern. The link's typed calls and the listener
thread are clients of it and share no socket state of their own.
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import encode_message
from punt_lux.tracing import trace

if TYPE_CHECKING:
    import socket

    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.protocol import Message, ReadyMessage

__all__ = ["DisplayConnection"]

_READ_CHUNK = 65536


@final
class DisplayConnection:
    """One display socket: dialed on open, written and read under a single lock."""

    _dialer: DisplayDialer
    _connect_timeout: float
    # None = not connected; the socket and its ready message come and go together.
    _sock: socket.socket | None
    _ready: ReadyMessage | None
    _lock: threading.Lock

    def __new__(cls, dialer: DisplayDialer, connect_timeout: float) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._sock = None
        self._ready = None
        self._lock = threading.Lock()
        return self

    @property
    def is_open(self) -> bool:
        """Whether a socket is currently held."""
        return self._sock is not None

    @property
    def ready(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` the handshake received, or ``None`` if not open."""
        return self._ready

    @property
    def current(self) -> socket.socket | None:
        """The socket held right now, or ``None`` -- it can change on reconnect."""
        return self._sock

    def open(self) -> None:
        """Dial the display and complete the handshake; a no-op if already open.

        Raises :class:`DisplayNotConnectedError` if the display cannot be
        reached or the handshake fails.
        """
        if self._sock is not None:
            return
        result = self._dialer.dial(self._connect_timeout)
        self._sock = result.sock
        self._ready = result.ready

    def close(self) -> None:
        """Close the socket, if open."""
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
            self._ready = None

    def require(self) -> socket.socket:
        """Return the open socket, or raise if the link was never connected."""
        if self._sock is None:
            msg = "Not connected — call connect() or use as context manager"
            raise RuntimeError(msg)
        return self._sock

    @trace
    def send(self, msg: Message) -> None:
        """Write ``msg`` to the open socket, serialized against other writers."""
        sock = self.require()
        wire = encode_message(msg)
        with self._lock:
            sock.sendall(wire)

    def read_chunk(self, sock: socket.socket) -> bytes:
        """Read what ``sock`` has available, serialized against writers.

        Empty bytes mean the display closed the connection; ``OSError``
        propagates for the listener to report.
        """
        with self._lock:
            return sock.recv(_READ_CHUNK)
