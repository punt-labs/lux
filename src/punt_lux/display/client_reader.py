"""ClientReader -- the recv / TLS-drain / frame / dispatch pipeline.

Extracted from :class:`~punt_lux.display.socket_server.SocketListener`
(PY-IC-6): reading bytes off a readable client socket, draining any
decrypted records OpenSSL buffered, reframing them, and dispatching each
complete message is one cohesive concern -- distinct from the accept,
identity, and send concerns the listener keeps. It reaches back into its
host only to remove a departed client and to test whether one is still
connected mid-dispatch, both narrowed to the :class:`ReaderHost` protocol.
"""

from __future__ import annotations

import logging
import socket
import ssl
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.protocol import HEADER_SIZE, MAX_MESSAGE_SIZE

if TYPE_CHECKING:
    from punt_lux.display.client_registry import ClientRegistry
    from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
    from punt_lux.display.socket_server import WantWriteState
    from punt_lux.protocol import FrameReader

logger = logging.getLogger(__name__)

__all__ = ["ClientReader", "ReaderHost"]

# One kernel read per pass; a promoted TLS socket's leftover records drain via
# pending() in the same pass rather than waiting on the next select wake-up.
_RECV_CHUNK = 65536


@runtime_checkable
class ReaderHost(Protocol):
    """What :class:`ClientReader` needs from the listener that owns it."""

    def remove_client(self, sock: socket.socket) -> None:
        """Drop a departed or malformed client and clean up its per-fd state."""
        ...

    def is_client(self, sock: socket.socket) -> bool:
        """Return whether ``sock`` is still a live registered client."""
        ...


@final
class ClientReader:
    """Reads framed messages off a readable client socket and dispatches them."""

    _registry: ClientRegistry
    _want_write: WantWriteState
    _callbacks: SocketListenerCallbacks
    _host: ReaderHost
    __slots__ = ("_callbacks", "_host", "_registry", "_want_write")

    def __new__(
        cls,
        *,
        registry: ClientRegistry,
        want_write: WantWriteState,
        callbacks: SocketListenerCallbacks,
        host: ReaderHost,
    ) -> Self:
        self = super().__new__(cls)
        self._registry = registry
        self._want_write = want_write
        self._callbacks = callbacks
        self._host = host
        return self

    def writable_sockets(
        self, fd_to_client: dict[int, socket.socket]
    ) -> list[socket.socket]:
        """Return the live sockets whose ``recv()`` is waiting on writability.

        The listener's ``poll_clients`` adds these to its write-select so a
        TLS ``recv()`` that raised ``SSLWantWriteError`` is retried once the
        socket can write, not left waiting on a read that will never come.
        """
        return self._want_write.sockets(fd_to_client)

    def forget(self, fd: int) -> None:
        """Drop ``fd`` from the want-write set -- a departed client is done."""
        self._want_write.set(fd, wants=False)

    def clear(self) -> None:
        """Drop every want-write fd -- shutdown, not one departure."""
        self._want_write.clear()

    def read(self, sock: socket.socket) -> None:
        """Read + dispatch; an SSL want-error means more I/O is needed, not death."""
        fd = sock.fileno()
        self._want_write.set(fd, wants=False)
        reader = self._registry.reader_for(fd)
        if reader is None:
            return
        try:
            data = sock.recv(_RECV_CHUNK)
            if not data:
                self._host.remove_client(sock)
                return
            reader.feed(data)
            self._drain_tls_backlog(sock, reader)
            self._dispatch(sock)
        except (ssl.SSLWantWriteError, ssl.SSLWantReadError) as exc:
            # want-write is tracked for the next write-select; a plain
            # want-read (not a full TLS record yet) just retries later.
            self._want_write.set(fd, wants=isinstance(exc, ssl.SSLWantWriteError))
        except (ConnectionError, OSError) as exc:
            self._callbacks.on_error("warning", str(exc), "client_connection")
            self._host.remove_client(sock)

    @staticmethod
    def _drain_tls_backlog(sock: socket.socket, reader: FrameReader) -> None:
        """Feed any decrypted records OpenSSL buffered while the fd is select-quiet.

        An :class:`ssl.SSLSocket` can hold one or more fully-decrypted records
        in its own buffer after ``recv()`` returns -- data the kernel fd no
        longer reports as readable, so ``select`` would never wake the poll
        loop to collect it. Draining ``pending()`` in the same read pass keeps
        a promoted cross-host frame from stranding until the next unrelated
        network event. A plain :class:`socket.socket` (the ``AF_UNIX`` leg)
        has no such buffer and is left untouched.
        """
        while isinstance(sock, ssl.SSLSocket) and sock.pending():
            more = sock.recv(_RECV_CHUNK)
            if not more:
                break
            reader.feed(more)

    def _dispatch(self, sock: socket.socket) -> None:
        """Drain every complete message ``sock``'s reader now holds and dispatch it."""
        fd = sock.fileno()
        reader = self._registry.reader_for(fd)
        if reader is None:
            return  # departed between read()'s feed and this call
        if reader.buffer_size > MAX_MESSAGE_SIZE + HEADER_SIZE:
            logger.warning("Buffer overflow from fd %d", fd)
            self._host.remove_client(sock)
            return
        try:
            messages = reader.drain_typed()
        except (ValueError, KeyError, TypeError) as exc:  # malformed wire data
            logger.warning("Malformed message from fd %d", fd)
            self._callbacks.on_error("error", str(exc), "message_parse")
            self._host.remove_client(sock)
            return
        for msg in messages:
            logger.debug("Received %s from fd=%s", type(msg).__name__, fd)
            self._callbacks.on_message(sock, msg)
            if not self._host.is_client(sock):
                return  # removed during handle (e.g. send failed)
