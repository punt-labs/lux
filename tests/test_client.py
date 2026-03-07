"""Unit tests for punt_lux.client — LuxClient connection and messaging."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    AckMessage,
    ClearMessage,
    InteractionMessage,
    Patch,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
    TextElement,
    UpdateMessage,
    recv_message,
    send_message,
)

# ---------------------------------------------------------------------------
# Helpers — mini display server for testing
# ---------------------------------------------------------------------------


def _verify_closed(client: LuxClient) -> None:
    """Assert client is disconnected (separate function to avoid mypy narrowing)."""
    assert not client.is_connected
    assert client.ready_message is None


def _mini_display(sock_path: Path, ready: threading.Event) -> socket.socket:
    """Start a mini display server that sends ReadyMessage on connect.

    Returns the server-side connection socket.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    ready.set()
    conn, _ = server.accept()
    send_message(conn, ReadyMessage())
    server.close()
    return conn


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnect:
    def test_connect_and_close(self, tmp_path: Path) -> None:
        """Client connects, receives ReadyMessage, then closes cleanly."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        server_conn: socket.socket | None = None
        ready_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()

            assert client.is_connected
            ready = client.ready_message
            assert ready is not None
            assert ready.version == "0.1"

            client.close()
            _verify_closed(client)
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_context_manager(self, tmp_path: Path) -> None:
        """LuxClient works as a context manager."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        server_conn: socket.socket | None = None
        ready_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                assert client.is_connected
            assert not client.is_connected
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_connect_no_server_raises(self, tmp_path: Path) -> None:
        """Connecting to a nonexistent socket raises RuntimeError."""
        sock_path = tmp_path / "nonexistent.sock"
        client = LuxClient(sock_path, auto_spawn=False)
        with pytest.raises(RuntimeError, match="Cannot connect"):
            client.connect()

    def test_double_connect_is_noop(self, tmp_path: Path) -> None:
        """Calling connect() twice doesn't crash."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        server_conn: socket.socket | None = None
        ready_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.connect()  # should be a no-op
            assert client.is_connected
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Sending messages
# ---------------------------------------------------------------------------


class TestSendMessages:
    def test_show_sends_scene(self, tmp_path: Path) -> None:
        """show() sends a SceneMessage and receives AckMessage."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            # Read the scene, send ack
            assert server_conn is not None
            msg = recv_message(server_conn, timeout=5)
            assert isinstance(msg, SceneMessage)
            assert msg.id == "s1"
            assert len(msg.elements) == 1
            send_message(server_conn, AckMessage(scene_id="s1", ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                ack = client.show(
                    "s1",
                    elements=[TextElement(id="t1", content="Hello")],
                    title="Test",
                )
                assert ack is not None
                assert ack.scene_id == "s1"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_show_buffers_interleaved_event(self, tmp_path: Path) -> None:
        """show() returns AckMessage even when a non-ack arrives first."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            msg = recv_message(server_conn, timeout=5)
            assert isinstance(msg, SceneMessage)
            # Send an interaction *before* the ack
            send_message(
                server_conn,
                InteractionMessage(
                    element_id="b1", action="click", ts=time.time(), value=True
                ),
            )
            send_message(server_conn, AckMessage(scene_id="s1", ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                ack = client.show(
                    "s1",
                    elements=[TextElement(id="t1", content="Hello")],
                )
                assert ack is not None
                assert ack.scene_id == "s1"
                # The interleaved interaction should be buffered for recv()
                buffered = client.recv(timeout=0.5)
                assert isinstance(buffered, InteractionMessage)
                assert buffered.element_id == "b1"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_update_sends_patches(self, tmp_path: Path) -> None:
        """update() sends an UpdateMessage and receives AckMessage."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            msg = recv_message(server_conn, timeout=5)
            assert isinstance(msg, UpdateMessage)
            assert msg.scene_id == "s1"
            assert len(msg.patches) == 1
            send_message(server_conn, AckMessage(scene_id="s1", ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                ack = client.update(
                    "s1",
                    patches=[Patch(id="t1", set={"content": "Updated"})],
                )
                assert ack is not None
                assert ack.scene_id == "s1"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_clear_sends_clear(self, tmp_path: Path) -> None:
        """clear() sends a ClearMessage (no ack expected)."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            msg = recv_message(server_conn, timeout=5)
            assert isinstance(msg, ClearMessage)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                client.clear()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_ping_pong(self, tmp_path: Path) -> None:
        """ping() sends PingMessage and receives PongMessage."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            msg = recv_message(server_conn, timeout=5)
            assert isinstance(msg, PingMessage)
            send_message(server_conn, PongMessage(ts=msg.ts, display_ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                pong = client.ping()
                assert isinstance(pong, PongMessage)
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Receiving events
# ---------------------------------------------------------------------------


class TestRecvEvents:
    def test_recv_interaction(self, tmp_path: Path) -> None:
        """recv() returns InteractionMessage sent by display."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            time.sleep(0.1)
            send_message(
                server_conn,
                InteractionMessage(
                    element_id="b1", action="click", ts=time.time(), value=True
                ),
            )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                msg = client.recv(timeout=2.0)
                assert isinstance(msg, InteractionMessage)
                assert msg.element_id == "b1"
                assert msg.action == "click"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_recv_timeout_returns_none(self, tmp_path: Path) -> None:
        """recv() returns None on timeout."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                msg = client.recv(timeout=0.2)
                assert msg is None
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_send_without_connect_raises(self) -> None:
        """Calling show() before connect() raises RuntimeError."""
        client = LuxClient(auto_spawn=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.show("s1", elements=[])

    def test_recv_without_connect_raises(self) -> None:
        """Calling recv() before connect() raises RuntimeError."""
        client = LuxClient(auto_spawn=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.recv()

    def test_close_without_connect_is_noop(self) -> None:
        """Calling close() without connecting doesn't crash."""
        client = LuxClient(auto_spawn=False)
        client.close()  # should not raise


# ---------------------------------------------------------------------------
# Auto-spawn
# ---------------------------------------------------------------------------


class TestAutoSpawn:
    def test_auto_spawn_calls_ensure_display(self, tmp_path: Path) -> None:
        """With auto_spawn=True, connect() calls ensure_display()."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with patch(
                "punt_lux.client.ensure_display", return_value=sock_path
            ) as mock_ensure:
                client = LuxClient(sock_path, auto_spawn=True, connect_timeout=2.0)
                client.connect()
                mock_ensure.assert_called_once_with(sock_path, timeout=2.0)
                client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)
