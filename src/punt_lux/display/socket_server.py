"""Unix socket server for non-blocking client multiplexing."""

from __future__ import annotations

import contextlib
import errno
import logging
import select
import socket
import ssl
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from punt_lux.bounded_send import BoundedSend
from punt_lux.display.client_registry import ClientRegistry
from punt_lux.display.nonblocking import Nonblocking
from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
from punt_lux.domain.identity import HubId
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    ReadyMessage,
    encode_message,
)

if TYPE_CHECKING:
    from punt_lux.protocol.messages import Message

__all__ = ["SocketListener", "SocketListenerCallbacks"]

logger = logging.getLogger(__name__)

# A full buffer drains in tens of ms once the peer reads -- this only bounds
# a genuinely stuck peer, absent a caller deadline.
_ONE_OFF_SEND_BUDGET = 1.0

# EADDRINUSE (Linux) / EEXIST (macOS/BSD): a concurrent binder won the race.
_BIND_RACE_ERRNOS = frozenset({errno.EADDRINUSE, errno.EEXIST})

# Large backlog so a briefly-stalled display (hung render loop, GPU stall)
# isn't misread as dead -- far beyond lux's real client count.
_LISTEN_BACKLOG = 128

# register_client_identity's hub_id default -- production callers
# (hub_reconciliation.py) always pass the sender's real HubId; this stands
# in for the many existing callers with no real Hub connection in play.
_DEFAULT_HUB_ID: HubId = HubId.stub()


class _WantWriteState:
    """Fds whose non-blocking ``recv()`` awaits writability (a TLS event, not death)."""

    _fds: set[int]
    __slots__ = ("_fds",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._fds = set()
        return self

    def set(self, fd: int, *, wants: bool) -> None:
        """Note whether ``fd``'s next ``recv()`` retry is waiting on writability."""
        (self._fds.add if wants else self._fds.discard)(fd)

    def discard(self, fd: int) -> None:
        """Clear ``fd`` -- a no-op if it was never tracked."""
        self._fds.discard(fd)

    def clear(self) -> None:
        """Drop every tracked fd -- shutdown, not one departure."""
        self._fds.clear()

    def sockets(self, fd_to_client: dict[int, socket.socket]) -> list[socket.socket]:
        """Return the live sockets among the tracked fds, for a write-select."""
        return list(map(fd_to_client.__getitem__, self._fds))


class SocketListener:
    """Accept/poll/read/send/remove clients; reactions delegate to callbacks."""

    _server_sock: socket.socket | None
    _clients: list[socket.socket]
    _registry: ClientRegistry
    _callbacks: SocketListenerCallbacks
    _frame_deadline: float | None  # bounds in-frame sends when set by the render loop
    _want_write: _WantWriteState

    def __new__(cls, callbacks: SocketListenerCallbacks) -> Self:
        self = super().__new__(cls)
        self._server_sock = None
        self._clients = []
        self._registry = ClientRegistry()
        self._callbacks = callbacks
        self._frame_deadline = None
        self._want_write = _WantWriteState()
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
        return self._registry.client_names

    @property
    def client_connect_times(self) -> dict[int, float]:
        """Return fd-to-connect-timestamp mapping."""
        return self._registry.client_connect_times

    @property
    def fd_to_client(self) -> dict[int, socket.socket]:
        """Return fd-to-socket mapping for O(1) lookup."""
        return self._registry.fd_to_client

    @property
    def client_count(self) -> int:
        """Return how many clients are currently connected."""
        return len(self._clients)

    # -- frame-scoped send budget -------------------------------------------

    @property
    def frame_deadline(self) -> float | None:
        """Return the deadline armed by :meth:`set_frame_deadline`, if any."""
        return self._frame_deadline

    def set_frame_deadline(self, deadline: float) -> None:
        """Bound every deadline-less send this frame against backpressure wedges."""
        self._frame_deadline = deadline

    def clear_frame_deadline(self) -> None:
        """Restore the one-off send budget for post-frame sends (screenshot, etc.)."""
        self._frame_deadline = None

    # -- lifecycle ----------------------------------------------------------

    def setup(self, socket_path: Path) -> bool:
        """Bind and listen; return ``False`` if a live display already owns it.

        Self-arbitrating under ``DisplayPaths.bind_lock``, so concurrent binders
        never unlink or bind over a live owner. A lost bind race
        (``EADDRINUSE``/``EEXIST``) returns ``False``; any other ``OSError`` fails loud.
        """
        dp = DisplayPaths(socket_path)
        with dp.bind_lock():
            if dp.is_running():
                logger.info("display already running at %s; exiting", socket_path)
                return False
            dp.cleanup_stale()  # unlinks only a confirmed-dead socket, under the lock
            socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            socket_path.parent.chmod(0o700)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(str(socket_path))
                sock.listen(_LISTEN_BACKLOG)
                Nonblocking.set(sock)
            except OSError as exc:
                sock.close()  # close on every failure path — never leak the bound fd
                if exc.errno not in _BIND_RACE_ERRNOS:
                    raise  # real failure (permissions, bad path, listen) fails loud
                logger.info("lost bind race at %s; exiting", socket_path)
                return False
            self._server_sock = sock
            return True

    def shutdown(self) -> None:
        """Close all client connections and the server socket."""
        for client in self._clients:
            with contextlib.suppress(OSError):
                client.close()
        self._clients.clear()
        self._registry.clear()
        self._want_write.clear()
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
            Nonblocking.set(conn)
            fd = conn.fileno()
            self._clients.append(conn)
            self._registry.register_connection(fd, conn)
            logger.debug("Client connected (total: %d)", self.client_count)
            self.send_to_client(conn, ReadyMessage())

    def poll_clients(self) -> None:
        """Read + dispatch from readable clients, plus any ``recv()``-wants-write fd."""
        if not self._clients:
            return
        watch_write = self._want_write.sockets(self._registry.fd_to_client)
        readable, writable, errored = select.select(
            self._clients, watch_write, self._clients, 0
        )
        for sock in errored:
            self.remove_client(sock)
        for sock in {*readable, *writable} & set(self._clients):
            self._read_from_client(sock)

    # -- client management --------------------------------------------------

    def remove_client(self, sock: socket.socket) -> None:
        """Remove a client socket and clean up per-client state."""
        if sock not in self._clients:
            return  # already removed -- make idempotent
        self._clients.remove(sock)
        fd = self._live_fd(sock)
        if fd is not None:
            self._registry.forget_connection(fd)
            self._want_write.discard(fd)
            self._callbacks.on_client_disconnected(fd)  # domain-specific cleanup
            # Popped last: a departure reaction (FrameBook/MenuReplica
            # cleanup) still resolves this fd's HubId via hub_id_of() here.
            self._registry.forget_hub_id(fd)
        with contextlib.suppress(OSError):
            sock.close()
        logger.debug("Client disconnected (remaining: %d)", self.client_count)

    @staticmethod
    def _live_fd(sock: socket.socket) -> int | None:
        """Return sock's fd if live, else None (a closed sock's is -1, not a raise)."""
        try:
            fd = sock.fileno()
        except OSError:
            fd = -1
        return fd if fd >= 0 else None

    def send_to_client(
        self, sock: socket.socket, msg: Message, deadline: float | None = None
    ) -> bool:
        """Send ``msg`` to ``sock`` before ``deadline``; return whether it landed.

        A caller-less send uses the armed frame deadline or its own one-off
        budget. A slow-but-alive peer (``BlockingIOError``) keeps the client and
        defers; only a dead peer (``OSError``) removes it.
        """
        if deadline is None:
            deadline = (
                self._frame_deadline
                if self._frame_deadline is not None
                else time.monotonic() + _ONE_OFF_SEND_BUDGET
            )
        try:
            BoundedSend().send(sock, encode_message(msg), deadline)
        except BlockingIOError:
            return False  # alive but slow past the deadline -- defer, do not remove
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "send failed (%s); dropped %s, removing client",
                type(exc).__name__,
                type(msg).__name__,
            )
            self.remove_client(sock)
            return False
        return True

    def register_client_identity(
        self,
        fd: int,
        *,
        kind: Literal["hub", "test"],
        name: str,
        connect_time: float,
        hub_id: HubId = _DEFAULT_HUB_ID,
    ) -> None:
        """Record a client's declared kind, name, ``HubId``, and connect time."""
        self._registry.identify(
            fd, kind=kind, name=name, hub_id=hub_id, connect_time=connect_time
        )

    def kind_of(self, fd: int) -> Literal["hub", "test"] | None:
        """Return the declared kind for ``fd``, or ``None`` before it identifies."""
        return self._registry.kind_of(fd)

    def hub_id_of(self, fd: int) -> HubId | None:
        """Return the declared ``HubId`` for ``fd``, or ``None`` if unidentified."""
        return self._registry.hub_id_of(fd)

    def hub_fd_for(self, hub_id: HubId) -> int | None:
        """Return the live fd currently declaring ``kind="hub"`` with this ``HubId``."""
        return self._registry.hub_fd_for(hub_id)

    # -- internal -----------------------------------------------------------

    def _read_from_client(self, sock: socket.socket) -> None:
        """Read + dispatch; an SSL want-error means more I/O is needed, not death."""
        fd = sock.fileno()
        self._want_write.discard(fd)
        reader = self._registry.reader_for(fd)
        if reader is None:
            return
        try:
            data = sock.recv(65536)
            if not data:
                self.remove_client(sock)
                return
            reader.feed(data)
            self._dispatch_ready_messages(sock)
        except (ssl.SSLWantWriteError, ssl.SSLWantReadError) as exc:
            # want-write is tracked for the next write-select; a plain
            # want-read (not a full TLS record yet) just retries later.
            self._want_write.set(fd, wants=isinstance(exc, ssl.SSLWantWriteError))
        except (ConnectionError, OSError) as exc:
            self._callbacks.on_error("warning", str(exc), "client_connection")
            self.remove_client(sock)

    def _dispatch_ready_messages(self, sock: socket.socket) -> None:
        """Drain every complete message ``sock``'s reader now holds and dispatch it."""
        fd = sock.fileno()
        reader = self._registry.reader_for(fd)
        if reader is None:
            return  # departed between _read_from_client's feed and this call
        if reader.buffer_size > MAX_MESSAGE_SIZE + HEADER_SIZE:
            logger.warning("Buffer overflow from fd %d", fd)
            self.remove_client(sock)
            return
        try:
            messages = reader.drain_typed()
        except (ValueError, KeyError, TypeError) as exc:  # malformed wire data
            logger.warning("Malformed message from fd %d", fd)
            self._callbacks.on_error("error", str(exc), "message_parse")
            self.remove_client(sock)
            return
        for msg in messages:
            logger.debug("Received %s from fd=%s", type(msg).__name__, fd)
            self._callbacks.on_message(sock, msg)
            if sock not in self._clients:
                return  # removed during handle (e.g. send failed)
