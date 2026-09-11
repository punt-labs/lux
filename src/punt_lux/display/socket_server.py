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
from typing import Literal, Self

from punt_lux.bounded_send import BoundedSend
from punt_lux.display.client_identity_book import ClientIdentityBook
from punt_lux.display.nonblocking import Nonblocking
from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    FrameReader,
    ReadyMessage,
    encode_message,
)
from punt_lux.protocol.messages import Message

__all__ = ["SocketListener", "SocketListenerCallbacks"]

logger = logging.getLogger(__name__)

# Budget for a one-off send (no caller deadline): a full buffer drains in tens of
# milliseconds once the peer reads, so this only bounds a genuinely stuck peer.
_ONE_OFF_SEND_BUDGET = 1.0

# AF_UNIX bind() rejects an already-owned path with EADDRINUSE on Linux and
# EEXIST on macOS/BSD; either means a concurrent binder won the race.
_BIND_RACE_ERRNOS = frozenset({errno.EADDRINUSE, errno.EEXIST})

# Large backlog so a briefly-stalled display (hung render loop, GPU stall,
# breakpoint) that is not draining accepts isn't misread as dead: a probe would
# get ECONNREFUSED only once 128+ connects are queued, far beyond lux's real
# client count (luxd's one persistent connection plus occasional probes).
_LISTEN_BACKLOG = 128


class SocketListener:
    """Accept, poll, read from, send to, and remove Unix socket clients.

    Pure networking -- no ImGui dependency.  Domain-specific reactions
    (scene ownership, menu cleanup) are delegated to callbacks.
    """

    _server_sock: socket.socket | None
    _clients: list[socket.socket]
    _readers: dict[int, FrameReader]
    _fd_to_client: dict[int, socket.socket]
    _identity: ClientIdentityBook
    _callbacks: SocketListenerCallbacks
    _frame_deadline: float | None  # bounds in-frame sends when set by the render loop
    _want_write: set[int]  # fds whose recv() wants writability (rare TLS event)

    def __new__(cls, callbacks: SocketListenerCallbacks) -> Self:
        self = super().__new__(cls)
        self._server_sock = None
        self._clients = []
        self._readers = {}
        self._fd_to_client = {}
        self._identity = ClientIdentityBook()
        self._callbacks = callbacks
        self._frame_deadline = None
        self._want_write = set()
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
        return self._identity.names

    @property
    def client_connect_times(self) -> dict[int, float]:
        """Return fd-to-connect-timestamp mapping."""
        return self._identity.connect_times

    @property
    def fd_to_client(self) -> dict[int, socket.socket]:
        """Return fd-to-socket mapping for O(1) lookup."""
        return self._fd_to_client

    # -- frame-scoped send budget -------------------------------------------

    def set_frame_deadline(self, deadline: float) -> None:
        """Bound every deadline-less send in this frame by ``deadline`` (monotonic).

        The render loop calls this at the top of each frame so a burst of Acks,
        Pongs, and query responses cannot stack per-send ``_ONE_OFF_SEND_BUDGET``
        waits into a multi-second wedge under Hub backpressure. Sends that pass an
        explicit deadline (interaction delivery already does so) are unaffected.
        """
        self._frame_deadline = deadline

    def clear_frame_deadline(self) -> None:
        """Restore the one-off send budget for post-frame sends (screenshot, etc.)."""
        self._frame_deadline = None

    # -- lifecycle ----------------------------------------------------------

    def setup(self, socket_path: Path) -> bool:
        """Bind and listen; return ``False`` if a live display already owns it.

        Self-arbitrating: the whole probe → stale-cleanup → ``bind`` → ``listen``
        critical section runs under ``DisplayPaths.bind_lock`` so concurrent
        binders serialize. Without that lock a racing caller can unlink a socket
        another process bound but has not yet listened on -- a freshly-bound
        socket refuses connections until ``listen``, so a probe reads it dead --
        letting two displays bind the same path. A live owner is never unlinked
        or bound over; a lost bind race (``EADDRINUSE``/``EEXIST``) returns
        ``False``; any other ``OSError`` fails loud.
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
            Nonblocking.set(conn)
            fd = conn.fileno()
            self._clients.append(conn)
            self._readers[fd] = FrameReader()
            self._fd_to_client[fd] = conn
            logger.debug("Client connected (total: %d)", len(self._clients))
            self.send_to_client(conn, ReadyMessage())

    def poll_clients(self) -> None:
        """Read + dispatch from readable clients, plus any ``recv()``-wants-write fd."""
        if not self._clients:
            return
        fd2sock = self._fd_to_client
        watch_write = [fd2sock[fd] for fd in self._want_write if fd in fd2sock]
        readable, writable, errored = select.select(
            self._clients, watch_write, self._clients, 0
        )
        for sock in errored:
            self.remove_client(sock)
        for sock in {*readable, *writable}:
            if sock in self._clients:
                self._read_from_client(sock)

    # -- client management --------------------------------------------------

    def remove_client(self, sock: socket.socket) -> None:
        """Remove a client socket and clean up per-client state."""
        if sock not in self._clients:
            return  # already removed -- make idempotent
        self._clients.remove(sock)
        fd = self._live_fd(sock)
        if fd is not None:
            self._readers.pop(fd, None)
            self._fd_to_client.pop(fd, None)
            self._identity.discard(fd)
            self._want_write.discard(fd)
            self._callbacks.on_client_disconnected(fd)  # domain-specific cleanup
        with contextlib.suppress(OSError):
            sock.close()
        logger.debug("Client disconnected (remaining: %d)", len(self._clients))

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

        The render loop passes one shared ``deadline`` so a frame's sends share a
        budget; a one-off send omits it and gets its own. When the render loop has
        armed a frame deadline (``set_frame_deadline``) the caller-less path uses
        that instead of the one-off budget, so a burst of in-frame Acks / Pongs /
        query responses cannot stack per-send waits into a multi-second wedge under
        Hub backpressure. A ``BlockingIOError`` (the peer alive but not drained
        before the deadline) keeps the client and reports ``False`` so the caller
        defers; only a dead-peer ``OSError`` removes it.
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
        self, fd: int, *, kind: Literal["hub", "test"], name: str, connect_time: float
    ) -> None:
        """Record a client's declared kind, display name, and connect timestamp."""
        self._identity.register(fd, kind=kind, name=name, connect_time=connect_time)

    def kind_of(self, fd: int) -> Literal["hub", "test"] | None:
        """Return the declared kind for ``fd``, or ``None`` before it identifies."""
        return self._identity.kind_of(fd)

    def hub_fd_for(self, name: str) -> int | None:
        """Return the live fd currently declaring ``kind="hub"`` with this name.

        See ``ClientIdentityBook.hub_fd_for`` -- the DES-068 preemption lookup.
        """
        return self._identity.hub_fd_for(name)

    # -- internal -----------------------------------------------------------

    def _read_from_client(self, sock: socket.socket) -> None:
        """Read available data from a client and dispatch complete messages.

        ``SSLWantReadError``/``SSLWantWriteError`` (checked ahead of the
        broader ``OSError`` they subclass) mean a non-blocking TLS socket
        wants more of a record -- not a dead peer. A want-write fd is
        tracked so the next ``poll_clients`` also selects it for
        writability; a plain want-read fd just retries on the next
        ordinary readable poll.
        """
        fd = sock.fileno()
        self._want_write.discard(fd)
        reader = self._readers.get(fd)
        if reader is None:
            return
        try:
            data = sock.recv(65536)
            if not data:
                self.remove_client(sock)
                return
            reader.feed(data)
            self._dispatch_ready_messages(sock)
        except ssl.SSLWantWriteError:
            self._want_write.add(fd)
        except ssl.SSLWantReadError:
            return  # not a full TLS record yet -- retry next readable poll
        except (ConnectionError, OSError) as exc:
            self._callbacks.on_error("warning", str(exc), "client_connection")
            self.remove_client(sock)

    def _dispatch_ready_messages(self, sock: socket.socket) -> None:
        """Drain every complete message ``sock``'s reader now holds and dispatch it."""
        fd = sock.fileno()
        reader = self._readers[fd]
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
