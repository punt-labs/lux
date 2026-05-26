"""Unit tests for punt_lux.display_client — DisplayClient connection and messaging."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.display_client import DisplayClient
from punt_lux.protocol import (
    AckMessage,
    ClearMessage,
    Patch,
    PingMessage,
    PongMessage,
    ReadyMessage,
    RegisterMenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    TextElement,
    UpdateMessage,
    encode_frame,
    recv_message,
    send_message,
)

# ---------------------------------------------------------------------------
# Helpers — mini display server for testing
# ---------------------------------------------------------------------------


def _verify_closed(client: DisplayClient) -> None:
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
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
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
        """DisplayClient works as a context manager."""
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
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
        client = DisplayClient(sock_path, auto_spawn=False)
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
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
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

    def test_show_drops_interleaved_event(self, tmp_path: Path) -> None:
        """show() returns AckMessage; interleaved non-ack frames are dropped."""
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
            # Send an interaction *before* the ack; without an active
            # listener and no registered callback there is no consumer,
            # so the new model drops it and proceeds to the ack.
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="b1", action="click", ts=time.time(), value=True
                ),
            )
            send_message(server_conn, AckMessage(scene_id="s1", ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                ack = client.show(
                    "s1",
                    elements=[TextElement(id="t1", content="Hello")],
                )
                assert ack is not None
                assert ack.scene_id == "s1"
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                client.clear()
            # Join BEFORE closing server_conn — the server thread may
            # still be inside recv_message's finally block restoring
            # sock.settimeout() when the main thread closes the fd.
            t.join(timeout=5)
        finally:
            if server_conn:
                server_conn.close()
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
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
    def test_interaction_dispatched_to_callback(self, tmp_path: Path) -> None:
        """Invocation delivery runs the registered on_event callback."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        received: list[RemoteEventHandlerInvocation] = []
        done = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            time.sleep(0.1)
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="b1", action="click", ts=time.time(), value=True
                ),
            )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)

            def _cb(msg: RemoteEventHandlerInvocation) -> None:
                received.append(msg)
                done.set()

            client.on_event("b1", "click", _cb)
            try:
                client.connect()
                client.start_listener()
                assert done.wait(timeout=2.0), "Callback never fired"
                assert received[0].element_id == "b1"
                assert received[0].action == "click"
            finally:
                client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_poll_event_timeout_raises(self, tmp_path: Path) -> None:
        """poll_event() raises TimeoutError when no event arrives in time."""
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                client.start_listener()
                with pytest.raises(TimeoutError):
                    client.poll_event(timeout=0.2)
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
        client = DisplayClient(auto_spawn=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.show("s1", elements=[])

    def test_poll_event_without_connect_raises(self) -> None:
        """Calling poll_event() before connect() raises RuntimeError."""
        client = DisplayClient(auto_spawn=False)
        with pytest.raises(RuntimeError, match="Not connected"):
            client.poll_event()

    def test_poll_event_after_listener_exit_raises_timeout(self) -> None:
        """A listener that started and exited surfaces as TimeoutError.

        The gate is ``_listener_thread is not None`` (it was started),
        not ``is_alive()`` — an exited listener is the no-event-arrived
        case with a clearer message, not a misuse RuntimeError.
        """
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
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                dead = threading.Thread(target=lambda: None)
                dead.start()
                dead.join()
                client._listener_thread = dead
                with pytest.raises(TimeoutError, match="listener thread has exited"):
                    client.poll_event(timeout=0.1)
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_close_without_connect_is_noop(self) -> None:
        """Calling close() without connecting doesn't crash."""
        client = DisplayClient(auto_spawn=False)
        client.close()  # should not raise


# ---------------------------------------------------------------------------
# Auto-spawn
# ---------------------------------------------------------------------------


class TestAutoSpawn:
    def test_auto_spawn_calls_ensure(self, tmp_path: Path) -> None:
        """With auto_spawn=True, connect() calls DisplayPaths.ensure()."""
        import tempfile

        from punt_lux.paths import DisplayPaths

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
            with patch.object(
                DisplayPaths, "ensure", return_value=sock_path
            ) as mock_ensure:
                client = DisplayClient(sock_path, auto_spawn=True, connect_timeout=2.0)
                client.connect()
                mock_ensure.assert_called_once_with(timeout=2.0)
                client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Menu registration
# ---------------------------------------------------------------------------


class TestRegisterMenuItem:
    def test_register_sends_accumulated_items(self, tmp_path: Path) -> None:
        """register_menu_item() sends a RegisterMenuMessage with all items."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        received: list[RegisterMenuMessage] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            # Read two RegisterMenuMessages (one per register_menu_item call)
            for _ in range(2):
                msg = recv_message(server_conn, timeout=5)
                assert isinstance(msg, RegisterMenuMessage)
                received.append(msg)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                client.register_menu_item({"id": "a", "label": "A"})
                client.register_menu_item({"id": "b", "label": "B"})
            t.join(timeout=5)
            assert len(received) == 2
            # First call: just item A
            assert len(received[0].items) == 1
            assert received[0].items[0]["id"] == "a"
            # Second call: items A and B accumulated
            assert len(received[1].items) == 2
            assert received[1].items[1]["id"] == "b"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_register_deduplicates_by_id(self, tmp_path: Path) -> None:
        """Registering an item with the same ID replaces the existing one."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        received: list[RegisterMenuMessage] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            for _ in range(2):
                msg = recv_message(server_conn, timeout=5)
                assert isinstance(msg, RegisterMenuMessage)
                received.append(msg)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            with DisplayClient(
                sock_path, auto_spawn=False, connect_timeout=2.0
            ) as client:
                client.register_menu_item({"id": "x", "label": "Old"})
                client.register_menu_item({"id": "x", "label": "New"})
            t.join(timeout=5)
            # Second message should have 1 item (deduped), with updated label
            assert len(received) == 2
            assert len(received[1].items) == 1
            assert received[1].items[0]["label"] == "New"
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_reconnect_replays_registered_items(self, tmp_path: Path) -> None:
        """connect() replays accumulated items after ReadyMessage handshake."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        replay_msg: list[RegisterMenuMessage] = []
        conns: list[socket.socket] = []

        def serve_two(server: socket.socket, ready: threading.Event) -> None:
            """Accept two connections, send ReadyMessage on each."""
            ready.set()
            for _ in range(2):
                conn, _ = server.accept()
                conns.append(conn)
                send_message(conn, ReadyMessage())

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(2)
        ready_event = threading.Event()
        t = threading.Thread(target=serve_two, args=(server, ready_event), daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            # First connection: register an item
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.register_menu_item({"id": "t1", "label": "Tool 1"})
            msg = recv_message(conns[0], timeout=5)
            assert isinstance(msg, RegisterMenuMessage)

            # Simulate disconnect + reconnect
            client.close()
            client.connect()
            replay = recv_message(conns[1], timeout=5)
            assert isinstance(replay, RegisterMenuMessage)
            replay_msg.append(replay)
            assert len(replay.items) == 1
            assert replay.items[0]["id"] == "t1"

            client.close()
        finally:
            for c in conns:
                c.close()
            server.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Background listener
# ---------------------------------------------------------------------------


class TestBackgroundListener:
    """Tests for push-based event handling via background listener."""

    def test_callback_dispatch(self) -> None:
        """Listener dispatches RemoteEventHandlerInvocation to registered callback."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        received: list[RemoteEventHandlerInvocation] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            time.sleep(0.1)
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="btn1", action="click", ts=time.time(), value=True
                ),
            )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.on_event("btn1", "click", lambda msg: received.append(msg))
            client.connect()
            client.start_listener()
            # Wait for callback to fire
            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(received) == 1
            assert received[0].element_id == "btn1"
            assert received[0].action == "click"
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_unmatched_interaction_and_unknown_are_dropped(self) -> None:
        """Unmatched interactions and unknown frames are dropped, not buffered."""
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
            # An interaction whose (element_id, action) has no callback.
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="other", action="click", ts=time.time(), value=True
                ),
            )
            # An unknown message type. Both fall through the dispatcher
            # without filling any queue, so poll_event sees nothing.
            server_conn.sendall(encode_frame({"type": "custom_event", "data": "hello"}))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.start_listener()
            # Listener has had time to drain both frames; poll_event sees
            # no business event and times out.
            time.sleep(0.3)
            with pytest.raises(TimeoutError):
                client.poll_event(timeout=0.2)
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_observer_message_routes_to_poll_event(self) -> None:
        """ObserverMessage payloads queue for poll_event consumption."""
        import tempfile

        from punt_lux.protocol import ObserverMessage

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
                ObserverMessage(topic="work.saved", payload={"id": "save_btn"}),
            )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.start_listener()
            event = client.poll_event(timeout=2.0)
            assert event.topic == "work.saved"
            assert event.payload == {"id": "save_btn"}
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_ack_routing_through_queue(self) -> None:
        """Acks route to _ack_queue so show() works with listener active."""
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
            send_message(server_conn, AckMessage(scene_id="s1", ts=time.time()))

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.start_listener()
            ack = client.show("s1", elements=[TextElement(id="t1", content="Hello")])
            assert ack is not None
            assert ack.scene_id == "s1"
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_show_async_from_callback(self) -> None:
        """show_async() works from inside a callback without deadlock."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        callback_done = threading.Event()
        server_received: list[SceneMessage] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            time.sleep(0.1)
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="trigger", action="click", ts=time.time(), value=True
                ),
            )
            # Read the scene sent by the callback
            msg = recv_message(server_conn, timeout=5)
            if isinstance(msg, SceneMessage):
                server_received.append(msg)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)

            def on_trigger(msg: RemoteEventHandlerInvocation) -> None:
                client.show_async(
                    "response",
                    elements=[TextElement(id="t1", content="Callback fired")],
                )
                callback_done.set()

            client.on_event("trigger", "click", on_trigger)
            client.connect()
            client.start_listener()
            assert callback_done.wait(timeout=2.0)
            # Give the server thread time to receive the scene
            t.join(timeout=2)
            assert len(server_received) == 1
            assert server_received[0].id == "response"
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_listener_survives_reconnect(self) -> None:
        """Listener restarts automatically after disconnect + reconnect."""
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        received: list[RemoteEventHandlerInvocation] = []
        conns: list[socket.socket] = []

        def serve_two(server: socket.socket, ready: threading.Event) -> None:
            ready.set()
            for i in range(2):
                conn, _ = server.accept()
                conns.append(conn)
                send_message(conn, ReadyMessage())
                if i == 1:
                    # Second connection: send an interaction
                    time.sleep(0.1)
                    send_message(
                        conn,
                        RemoteEventHandlerInvocation(
                            element_id="btn2",
                            action="click",
                            ts=time.time(),
                            value=True,
                        ),
                    )

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(2)
        ready_event = threading.Event()
        t = threading.Thread(target=serve_two, args=(server, ready_event), daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.on_event("btn2", "click", lambda msg: received.append(msg))
            client.connect()
            client.start_listener()
            assert client.listener_active

            # Disconnect
            client.close()
            stopped = not client.listener_active
            assert stopped

            # Reconnect — listener should auto-restart because callbacks exist
            client.connect()
            restarted = client.listener_active
            assert restarted

            # Wait for callback to fire
            deadline = time.monotonic() + 2.0
            while not received and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(received) == 1
            assert received[0].element_id == "btn2"
            client.close()
        finally:
            for c in conns:
                c.close()
            server.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_action_mismatch_is_dropped(self) -> None:
        """Callback keyed on (id, 'click') ignores (id, 'changed') events.

        The unmatched 'changed' event is dropped (no combined queue
        survives in the new dispatch model); only the matching 'click'
        runs the registered callback.
        """
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        click_received: list[RemoteEventHandlerInvocation] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            time.sleep(0.1)
            # Send a "changed" event — should NOT match the "click" callback
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="slider1",
                    action="changed",
                    ts=time.time(),
                    value=0.5,
                ),
            )
            # Send a "click" event — SHOULD match
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="slider1",
                    action="click",
                    ts=time.time(),
                    value=True,
                ),
            )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.on_event("slider1", "click", lambda msg: click_received.append(msg))
            client.connect()
            client.start_listener()

            # Wait for callback
            deadline = time.monotonic() + 2.0
            while not click_received and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(click_received) == 1
            assert click_received[0].action == "click"

            # The "changed" event was dropped; no business event is queued.
            with pytest.raises(TimeoutError):
                client.poll_event(timeout=0.2)
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_hello_world_menu_callback(self) -> None:
        """E2E proof: menu click → callback → show_async opens a frame.

        Simulates the full pipeline: a plugin registers a menu item,
        a user clicks it, the callback fires show_async to display
        "Hello World!" in a frame.
        """
        import tempfile

        short_dir = tempfile.mkdtemp(prefix="lux-")
        sock_path = Path(short_dir) / "d.sock"
        ready_event = threading.Event()
        server_conn: socket.socket | None = None
        callback_fired = threading.Event()
        server_received: list[SceneMessage] = []

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display(sock_path, ready_event)
            assert server_conn is not None
            # Read the RegisterMenuMessage from the client
            reg = recv_message(server_conn, timeout=5)
            assert isinstance(reg, RegisterMenuMessage)
            # Simulate user clicking the "Hello" menu item
            send_message(
                server_conn,
                RemoteEventHandlerInvocation(
                    element_id="hello-world",
                    action="menu",
                    ts=time.time(),
                    value={"item": "Hello", "menu": "Applications"},
                ),
            )
            # Read the SceneMessage sent by the callback
            scene = recv_message(server_conn, timeout=5)
            if isinstance(scene, SceneMessage):
                server_received.append(scene)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        ready_event.wait(timeout=5)

        try:
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)

            def on_hello(msg: RemoteEventHandlerInvocation) -> None:
                client.show_async(
                    "hello-scene",
                    elements=[
                        TextElement(id="greeting", content="Hello World!"),
                    ],
                    frame_id="hello-frame",
                    frame_title="Greeting",
                )
                callback_fired.set()

            client.on_event("hello-world", "menu", on_hello)
            client.connect()
            client.start_listener()
            # Register the menu item (triggers the flow)
            client.register_menu_item({"id": "hello-world", "label": "Hello"})
            # Wait for the full pipeline to complete
            assert callback_fired.wait(timeout=3.0), "Callback never fired"
            t.join(timeout=3)
            assert len(server_received) == 1
            scene = server_received[0]
            assert scene.id == "hello-scene"
            assert scene.frame_id == "hello-frame"
            assert len(scene.elements) == 1
            assert isinstance(scene.elements[0], TextElement)
            assert scene.elements[0].content == "Hello World!"
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)

    def test_poll_event_timeout_with_listener(self) -> None:
        """poll_event() raises TimeoutError when no event arrives via listener."""
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
            client = DisplayClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            client.start_listener()
            with pytest.raises(TimeoutError):
                client.poll_event(timeout=0.2)
            client.close()
        finally:
            if server_conn:
                server_conn.close()
            t.join(timeout=2)
            import shutil

            shutil.rmtree(short_dir, ignore_errors=True)
