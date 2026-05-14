"""Unit tests for punt_lux.socket_server — SocketServer lifecycle and I/O."""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

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
