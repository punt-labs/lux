"""Unit tests for punt_lux.socket_server — SocketServer lifecycle and I/O."""

from __future__ import annotations

import errno
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    ReadyMessage,
    SceneMessage,
    TextElement,
    recv_message,
    send_message,
)
from punt_lux.socket_server import SocketServer

if TYPE_CHECKING:
    from punt_lux.protocol.messages import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tmpdir() -> str:
    """Create a short temp directory for AF_UNIX paths (macOS 104-char limit)."""
    return tempfile.mkdtemp(prefix="lux-")


def _noop_message(_sock: socket.socket, _msg: Message) -> None:
    """No-op message callback."""


def _noop_disconnect(_fd: int) -> None:
    """No-op disconnect callback."""


def _noop_error(_sev: str, _msg: str, _ctx: str) -> None:
    """No-op error callback."""


def _make_server() -> SocketServer:
    """Create a SocketServer with no-op callbacks."""
    return SocketServer(
        on_message=_noop_message,
        on_client_disconnected=_noop_disconnect,
        on_error=_noop_error,
    )


def _connect_client(sock_path: Path) -> socket.socket:
    """Connect a blocking client to the server socket."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock_path))
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetup:
    """SocketServer.setup creates and binds the listening socket."""

    def test_setup_creates_socket(self) -> None:
        tmpdir = _make_tmpdir()
        sock_path = Path(tmpdir) / "test.sock"
        server = _make_server()
        try:
            server.setup(sock_path)
            assert sock_path.exists()
            assert sock_path.is_socket()
            assert server.server_sock is not None
        finally:
            server.shutdown()


class TestAcceptAndPoll:
    """SocketServer accepts clients and dispatches messages."""

    def test_accept_and_poll(self) -> None:
        tmpdir = _make_tmpdir()
        sock_path = Path(tmpdir) / "test.sock"
        received: list[tuple[int, Message]] = []

        def on_message(sock: socket.socket, msg: Message) -> None:
            received.append((sock.fileno(), msg))

        server = SocketServer(
            on_message=on_message,
            on_client_disconnected=_noop_disconnect,
            on_error=_noop_error,
        )
        try:
            server.setup(sock_path)

            # Connect a client
            client = _connect_client(sock_path)
            try:
                server.accept_connections()

                assert len(server.clients) == 1
                assert server.clients[0].fileno() in server.fd_to_client

                # Client receives ReadyMessage on connect
                ready = recv_message(client, timeout=2.0)
                assert isinstance(ready, ReadyMessage)

                # Send a scene message from client to server
                scene = SceneMessage(
                    id="s1",
                    elements=[TextElement(id="t1", content="hello")],
                )
                send_message(client, scene)

                # Poll to read it
                server.poll_clients()
                assert len(received) == 1
                _, msg = received[0]
                assert isinstance(msg, SceneMessage)
                assert msg.id == "s1"
            finally:
                client.close()
        finally:
            server.shutdown()


class TestRemoveClient:
    """SocketServer.remove_client cleans up all per-client state."""

    def test_remove_client_cleanup(self) -> None:
        tmpdir = _make_tmpdir()
        sock_path = Path(tmpdir) / "test.sock"
        disconnected_fds: list[int] = []

        def on_disconnect(fd: int) -> None:
            disconnected_fds.append(fd)

        server = SocketServer(
            on_message=_noop_message,
            on_client_disconnected=on_disconnect,
            on_error=_noop_error,
        )
        try:
            server.setup(sock_path)
            client = _connect_client(sock_path)
            try:
                server.accept_connections()
                assert len(server.clients) == 1

                conn = server.clients[0]
                fd = conn.fileno()

                # Register a name so we can verify cleanup
                server.register_client_name(fd, "test-client", 1000.0)
                assert fd in server.client_names
                assert fd in server.client_connect_times

                server.remove_client(conn)

                assert len(server.clients) == 0
                assert fd not in server.fd_to_client
                assert fd not in server.client_names
                assert fd not in server.client_connect_times
                assert len(disconnected_fds) == 1
                assert disconnected_fds[0] == fd
            finally:
                client.close()
        finally:
            server.shutdown()


class TestSendToClient:
    """SocketServer.send_to_client delivers messages over the wire."""

    def test_send_to_client(self) -> None:
        tmpdir = _make_tmpdir()
        sock_path = Path(tmpdir) / "test.sock"
        server = _make_server()
        try:
            server.setup(sock_path)
            client = _connect_client(sock_path)
            try:
                server.accept_connections()

                # Drain the ReadyMessage that accept sends automatically
                ready = recv_message(client, timeout=2.0)
                assert isinstance(ready, ReadyMessage)

                # Now send a custom message
                conn = server.clients[0]
                scene = SceneMessage(
                    id="s2",
                    elements=[TextElement(id="t2", content="world")],
                )
                server.send_to_client(conn, scene)

                msg = recv_message(client, timeout=2.0)
                assert isinstance(msg, SceneMessage)
                assert msg.id == "s2"
                assert len(msg.elements) == 1
            finally:
                client.close()
        finally:
            server.shutdown()

    def test_remove_idempotent(self) -> None:
        """Calling remove_client twice does not raise."""
        tmpdir = _make_tmpdir()
        sock_path = Path(tmpdir) / "test.sock"
        server = _make_server()
        try:
            server.setup(sock_path)
            client = _connect_client(sock_path)
            try:
                server.accept_connections()
                conn = server.clients[0]
                server.remove_client(conn)
                # Second call is a no-op
                server.remove_client(conn)
                assert len(server.clients) == 0
            finally:
                client.close()
        finally:
            server.shutdown()


class _BindRaises:
    """Fake socket whose bind raises a chosen ``OSError`` — for the race window."""

    _errno: int

    def __new__(cls, errno_val: int) -> _BindRaises:
        self = super().__new__(cls)
        self._errno = errno_val
        return self

    def bind(self, _addr: str) -> None:
        raise OSError(self._errno, os.strerror(self._errno))

    def close(self) -> None:
        """No-op close so ``setup`` can release the failed socket."""


def _always_dead(_self: DisplayPaths) -> bool:
    """Force the liveness probe to report DEAD (simulate the race window)."""
    return False


def _skip_cleanup(_self: DisplayPaths) -> None:
    """No-op cleanup so a pre-bound race socket survives to the bind."""


def _bind_eacces(*_args: object, **_kwargs: object) -> _BindRaises:
    """Socket factory whose bind fails with a non-race ``EACCES``."""
    return _BindRaises(errno.EACCES)


class TestSetupArbitration:
    """setup() self-arbitrates: exactly one binder wins, live owners survive."""

    def test_returns_true_on_cold_bind(self) -> None:
        """A cold path binds and serves, reporting True."""
        sock_path = Path(_make_tmpdir()) / "test.sock"
        server = _make_server()
        try:
            assert server.setup(sock_path) is True
            assert server.server_sock is not None
            assert sock_path.is_socket()
        finally:
            server.shutdown()

    def test_returns_false_and_preserves_live_owner(self) -> None:
        """A second setup on a live socket reports False and never unlinks it."""
        sock_path = Path(_make_tmpdir()) / "test.sock"
        owner = _make_server()
        intruder = _make_server()
        try:
            assert owner.setup(sock_path) is True
            owner_fd = owner.server_sock.fileno() if owner.server_sock else -1

            assert intruder.setup(sock_path) is False
            assert intruder.server_sock is None

            # The live owner's socket is untouched and still answering.
            assert sock_path.is_socket()
            assert owner.server_sock is not None
            assert owner.server_sock.fileno() == owner_fd
            assert DisplayPaths(sock_path).is_running()
        finally:
            intruder.shutdown()
            owner.shutdown()

    def test_rebinds_over_stale_socket(self) -> None:
        """A dead leftover socket is cleaned and rebound — normal cold start."""
        sock_path = Path(_make_tmpdir()) / "test.sock"
        # A bound-but-closed socket leaves a stale file with no listener.
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(sock_path))
        stale.close()
        assert sock_path.is_socket()  # file survives close()

        server = _make_server()
        try:
            assert server.setup(sock_path) is True
            assert server.server_sock is not None
        finally:
            server.shutdown()

    def test_returns_false_on_bind_race(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An EADDRINUSE at bind (concurrent winner) reports False, not an error."""
        sock_path = Path(_make_tmpdir()) / "test.sock"
        # A concurrent display bound the path in the window after our probe;
        # simulate by pre-binding and forcing the probe/cleanup to see nothing.
        winner = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        winner.bind(str(sock_path))
        winner.listen(5)
        monkeypatch.setattr(DisplayPaths, "is_running", _always_dead)
        monkeypatch.setattr(DisplayPaths, "cleanup_stale", _skip_cleanup)

        server = _make_server()
        try:
            assert server.setup(sock_path) is False
            assert server.server_sock is None
            assert sock_path.is_socket()  # the winner's socket is intact
        finally:
            server.shutdown()
            winner.close()

    def test_propagates_non_race_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A bind failure that is not a lost race fails loud, not a False return."""
        sock_path = Path(_make_tmpdir()) / "test.sock"
        monkeypatch.setattr(DisplayPaths, "is_running", _always_dead)
        monkeypatch.setattr(DisplayPaths, "cleanup_stale", _skip_cleanup)
        monkeypatch.setattr(socket, "socket", _bind_eacces)

        server = _make_server()
        with pytest.raises(OSError) as exc_info:
            server.setup(sock_path)
        assert exc_info.value.errno == errno.EACCES
        assert server.server_sock is None

    def test_closes_socket_on_post_bind_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A listen() failure after a successful bind closes the fd and re-raises.

        A post-bind failure (resource exhaustion) must not leak the bound
        socket. setup wraps bind+listen+setblocking so any OSError closes the
        socket before propagating; a non-race errno still fails loud.
        """
        sock_path = Path(_make_tmpdir()) / "test.sock"
        created: list[socket.socket] = []
        real_socket = socket.socket

        def tracking_socket(family: int, type_: int) -> socket.socket:
            sock = real_socket(family, type_)
            created.append(sock)
            return sock

        def failing_listen(_self: socket.socket, _backlog: int) -> None:
            raise OSError(errno.ENOMEM, "cannot allocate memory")

        monkeypatch.setattr(socket, "socket", tracking_socket)
        monkeypatch.setattr(real_socket, "listen", failing_listen)

        server = _make_server()
        with pytest.raises(OSError) as exc_info:
            server.setup(sock_path)
        assert exc_info.value.errno == errno.ENOMEM  # non-race failure fails loud
        assert server.server_sock is None  # no half-open server retained
        assert created  # the server socket was created
        assert created[-1].fileno() == -1  # ...and closed, not leaked

    def test_concurrent_setup_single_winner(self) -> None:
        """Many threads racing on one path: exactly one binds and serves.

        Repeated across rounds because the bind→listen window is timing
        dependent; a single round can pass by luck. Each round uses a fresh
        path and a tight barrier so all threads enter ``setup`` together.
        """
        for _ in range(4):
            self._assert_single_winner(thread_count=10)

    @staticmethod
    def _assert_single_winner(*, thread_count: int) -> None:
        """Race ``thread_count`` setups on one path; assert exactly one wins.

        The winner mimics the render loop by draining its accept backlog: a
        bound socket that never accepts would fill ``listen()`` and start
        refusing the losers' liveness probes, making a live winner look dead.
        """
        sock_path = Path(_make_tmpdir()) / "test.sock"
        servers = [_make_server() for _ in range(thread_count)]
        results: list[bool] = []
        lock = threading.Lock()
        start = threading.Barrier(thread_count)
        stop = threading.Event()

        def attempt(srv: SocketServer) -> None:
            start.wait()  # release all threads at once to maximize contention
            won = srv.setup(sock_path)
            with lock:
                results.append(won)
            while won and not stop.wait(0.002):
                srv.accept_connections()  # drain the backlog like the render loop

        threads = [threading.Thread(target=attempt, args=(s,)) for s in servers]
        for t in threads:
            t.start()
        try:
            deadline = time.monotonic() + 20.0
            while len(results) < thread_count and time.monotonic() < deadline:
                time.sleep(0.01)
            assert results.count(True) == 1
            assert results.count(False) == thread_count - 1
            assert sum(s.server_sock is not None for s in servers) == 1
            # The one live socket is the winner's — it answers a liveness probe.
            assert DisplayPaths(sock_path).is_running()
        finally:
            stop.set()
            for t in threads:
                t.join(timeout=10.0)
                assert not t.is_alive(), "a racing setup thread never terminated"
            for s in servers:
                s.shutdown()

    def test_stalled_server_not_misread_as_dead(self) -> None:
        """A bound server with many unaccepted connects still probes live.

        Connects queued below the listen backlog do not exhaust it, so a
        liveness probe still connects instead of getting ECONNREFUSED -- a
        briefly-stalled display (not draining accepts) is not misread as dead.
        With the old backlog of 5, this many queued connects would refuse the
        probe and the live server would read as dead.
        """
        sock_path = Path(_make_tmpdir()) / "test.sock"
        server = _make_server()
        pending: list[socket.socket] = []
        try:
            assert server.setup(sock_path) is True
            for _ in range(20):  # a stalled render loop never accepts these
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(str(sock_path))
                pending.append(client)
            assert DisplayPaths(sock_path).is_running()  # live, not refused
        finally:
            for client in pending:
                client.close()
            server.shutdown()

    def test_bind_lock_blocks_concurrent_setup(self) -> None:
        """Holding the bind lock stalls a concurrent setup until it is released.

        Directly exercises the bind→listen window: while one caller owns the
        bind lock, a second ``setup`` cannot probe-cleanup-bind, so it cannot
        unlink or bind over the first. It proceeds only once the lock frees.
        """
        sock_path = Path(_make_tmpdir()) / "test.sock"
        dp = DisplayPaths(sock_path)
        server = _make_server()
        result: list[bool] = []
        entered = threading.Event()

        def attempt() -> None:
            entered.set()
            result.append(server.setup(sock_path))

        try:
            with dp.bind_lock():
                worker = threading.Thread(target=attempt)
                worker.start()
                assert entered.wait(timeout=2)
                worker.join(timeout=0.5)
                assert worker.is_alive()  # blocked on the bind lock
                assert server.server_sock is None  # nothing bound yet
            worker.join(timeout=5)
            assert not worker.is_alive(), "concurrent setup hung after lock release"
            assert result == [True]  # bound only after the lock was released
            assert server.server_sock is not None
        finally:
            server.shutdown()

    def test_fresh_bind_survives_concurrent_setup_in_window(self) -> None:
        """A freshly bound (not-yet-listening) socket is never unlinked mid-window.

        The round-2 defect was a concurrent cleanup unlinking a socket another
        process had bound but not yet listened on. A binder holds the bind lock
        and binds without ``listen`` — the exact window. A concurrent ``setup``
        must block on the bind lock, so it can neither unlink the fresh bind nor
        bind over it. The inode is unchanged and the concurrent setup has bound
        nothing until the lock frees; only then does exactly one binder proceed.
        This is the executable counterpart of the model's buggy-variant
        counterexample.
        """
        sock_path = Path(_make_tmpdir()) / "test.sock"
        dp = DisplayPaths(sock_path)
        server = _make_server()
        fresh = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        result: list[bool] = []
        entered = threading.Event()
        worker: threading.Thread | None = None

        def concurrent_setup() -> None:
            entered.set()
            result.append(server.setup(sock_path))

        try:
            with dp.bind_lock():
                fresh.bind(str(sock_path))  # bound, no listen() — the window
                bound_inode = sock_path.stat().st_ino
                worker = threading.Thread(target=concurrent_setup)
                worker.start()
                assert entered.wait(timeout=2)
                worker.join(timeout=0.5)
                assert worker.is_alive()  # blocked on the bind lock
                # Cleanup cannot run: the fresh bind's inode is untouched.
                assert sock_path.stat().st_ino == bound_inode
                assert server.server_sock is None  # concurrent setup bound nothing
            worker.join(timeout=5)
            assert not worker.is_alive(), "concurrent setup hung after lock release"
            assert result == [True]  # exactly one winner, only after the lock freed
            assert server.server_sock is not None
        finally:
            fresh.close()
            server.shutdown()
            if worker is not None:
                worker.join(timeout=5)
