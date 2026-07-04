"""Unix socket server for non-blocking client multiplexing."""

from __future__ import annotations

import contextlib
import errno
import logging
import select
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Self

from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    FrameReader,
    ReadyMessage,
    encode_message,
)
from punt_lux.protocol.messages import Message

logger = logging.getLogger(__name__)

# AF_UNIX bind() rejects an already-owned path with EADDRINUSE on Linux and
# EEXIST on macOS/BSD; either means a concurrent binder won the race.
_BIND_RACE_ERRNOS = frozenset({errno.EADDRINUSE, errno.EEXIST})


class SocketServer:
    """Accept, poll, read from, send to, and remove Unix socket clients.

    Pure networking -- no ImGui dependency.  Domain-specific reactions
    (scene ownership, menu cleanup) are delegated to callbacks.
    """

    _server_sock: socket.socket | None
    _clients: list[socket.socket]
    _readers: dict[int, FrameReader]
    _fd_to_client: dict[int, socket.socket]
    _client_names: dict[int, str]
    _client_connect_times: dict[int, float]
    _on_message: Callable[[socket.socket, Message], None]
    _on_client_disconnected: Callable[[int], None]
    _on_error: Callable[[str, str, str], None]

    def __new__(
        cls,
        on_message: Callable[[socket.socket, Message], None],
        on_client_disconnected: Callable[[int], None],
        on_error: Callable[[str, str, str], None],
    ) -> Self:
        self = super().__new__(cls)
        self._server_sock = None
        self._clients = []
        self._readers = {}
        self._fd_to_client = {}
        self._client_names = {}
        self._client_connect_times = {}
        self._on_message = on_message
        self._on_client_disconnected = on_client_disconnected
        self._on_error = on_error
        return self

    # -- public properties --------------------------------------------------

    @property
    def server_sock(self) -> socket.socket | None:
        """Return the listening socket, or ``None`` before setup."""
        return self._server_sock

    @property
    def clients(self) -> list[socket.socket]:
        """Return the list of connected client sockets."""
        return self._clients

    @property
    def client_names(self) -> dict[int, str]:
        """Return fd-to-display-name mapping."""
        return self._client_names

    @property
    def client_connect_times(self) -> dict[int, float]:
        """Return fd-to-connect-timestamp mapping."""
        return self._client_connect_times

    @property
    def fd_to_client(self) -> dict[int, socket.socket]:
        """Return fd-to-socket mapping for O(1) lookup."""
        return self._fd_to_client

    # -- lifecycle ----------------------------------------------------------

    def setup(self, socket_path: Path) -> bool:
        """Bind and listen; return ``False`` if a live display already owns it.

        Self-arbitrating: a live owner is never unlinked or bound over, and
        ``bind()`` is the mutex, so an ``EADDRINUSE`` loss means a concurrent
        display won the race between the probe and this bind. Raise on a
        genuine bind failure.
        """
        dp = DisplayPaths(socket_path)
        if dp.is_running():
            logger.info("display already running at %s; exiting", socket_path)
            return False
        dp.cleanup_stale()  # unlinks only a confirmed-dead socket (re-probe guarded)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        socket_path.parent.chmod(0o700)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(socket_path))
        except OSError as exc:
            sock.close()
            if exc.errno not in _BIND_RACE_ERRNOS:
                raise  # a real bind failure (permissions, bad path) fails loud
            logger.info("lost bind race at %s; exiting", socket_path)
            return False
        sock.listen(5)
        sock.setblocking(False)  # noqa: FBT003
        self._server_sock = sock
        return True

    def shutdown(self) -> None:
        """Close all client connections and the server socket."""
        for client in self._clients:
            with contextlib.suppress(OSError):
                client.close()
        self._clients.clear()
        self._readers.clear()
        self._fd_to_client.clear()
        if self._server_sock is not None:
            self._server_sock.close()
            self._server_sock = None

    # -- per-frame operations -----------------------------------------------

    def accept_connections(self) -> None:
        """Accept any pending client connections (non-blocking)."""
        if self._server_sock is None:
            return
        readable, _, _ = select.select([self._server_sock], [], [], 0)
        if readable:
            try:
                conn, _ = self._server_sock.accept()
            except (BlockingIOError, OSError):
                return
            conn.setblocking(False)  # noqa: FBT003
            fd = conn.fileno()
            self._clients.append(conn)
            self._readers[fd] = FrameReader()
            self._fd_to_client[fd] = conn
            logger.debug("Client connected (total: %d)", len(self._clients))
            self.send_to_client(conn, ReadyMessage())

    def poll_clients(self) -> None:
        """Read from all readable clients and dispatch messages."""
        if not self._clients:
            return
        readable, _, errored = select.select(self._clients, [], self._clients, 0)
        for sock in errored:
            self.remove_client(sock)
        for sock in readable:
            if sock in self._clients:
                self._read_from_client(sock)

    # -- client management --------------------------------------------------

    def remove_client(self, sock: socket.socket) -> None:
        """Remove a client socket and clean up per-client state."""
        if sock not in self._clients:
            return  # already removed -- make idempotent
        self._clients.remove(sock)
        try:
            fd = sock.fileno()
        except OSError:
            fd = None
            logger.warning("Client socket fd unavailable -- skipping cleanup")
        if fd is not None:
            self._readers.pop(fd, None)
            self._fd_to_client.pop(fd, None)
            self._client_names.pop(fd, None)
            self._client_connect_times.pop(fd, None)
            # Let the owner handle domain-specific cleanup
            self._on_client_disconnected(fd)
        with contextlib.suppress(OSError):
            sock.close()
        logger.debug("Client disconnected (remaining: %d)", len(self._clients))

    def send_to_client(self, sock: socket.socket, msg: Message) -> None:
        """Send a protocol message to a client, removing on failure."""
        try:
            sock.sendall(encode_message(msg))
        except (ConnectionError, OSError):
            self.remove_client(sock)

    def register_client_name(self, fd: int, name: str, connect_time: float) -> None:
        """Record a client's display name and connect timestamp."""
        self._client_names[fd] = name
        self._client_connect_times[fd] = connect_time

    # -- internal -----------------------------------------------------------

    def _read_from_client(self, sock: socket.socket) -> None:
        """Read available data from a client and dispatch complete messages."""
        reader = self._readers.get(sock.fileno())
        if reader is None:
            return
        try:
            data = sock.recv(65536)
            if not data:
                self.remove_client(sock)
                return
            reader.feed(data)
            if reader.buffer_size > MAX_MESSAGE_SIZE + HEADER_SIZE:
                logger.warning("Buffer overflow from fd %d", sock.fileno())
                self.remove_client(sock)
                return
            # Deserialize all complete frames -- KeyError/TypeError/ValueError
            # here means malformed wire data, not a handler bug.
            try:
                messages = reader.drain_typed()
            except (ValueError, KeyError, TypeError) as exc:
                fd = sock.fileno()
                logger.warning("Malformed message from fd %d", fd)
                self._on_error("error", str(exc), "message_parse")
                self.remove_client(sock)
                return
            for msg in messages:
                logger.debug(
                    "Received %s from fd=%s", type(msg).__name__, sock.fileno()
                )
                self._on_message(sock, msg)
                if sock not in self._clients:
                    return  # removed during handle (e.g. send failed)
        except (ConnectionError, OSError) as exc:
            self._on_error("warning", str(exc), "client_connection")
            self.remove_client(sock)
