"""Integration tests: socket IPC, protocol framing.

These tests use real Unix domain sockets but no display process.
Run with: uv run pytest -m integration
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from punt_lux import decode_frame, encode_frame
from punt_lux.client import LuxClient
from punt_lux.protocol import (
    AckMessage,
    ReadyMessage,
    SceneMessage,
    TextElement,
    recv_message,
    send_message,
)

NUM_RAPID_SCENES = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_sock_path() -> tuple[str, Path]:
    """Create a short temp dir + socket path (Unix sockets have ~104 char limit)."""
    d = tempfile.mkdtemp(prefix="lux-")
    return d, Path(d) / "d.sock"


def _cleanup(short_dir: str, *socks: socket.socket | None) -> None:
    import contextlib
    import shutil

    for s in socks:
        if s is not None:
            with contextlib.suppress(OSError):
                s.close()
    shutil.rmtree(short_dir, ignore_errors=True)


def _mini_display_server(
    sock_path: Path,
    ready: threading.Event,
) -> socket.socket:
    """Start a mini display that sends ReadyMessage on connect.

    Returns the server-side connection socket.  The listener socket is
    closed before returning — only one client is accepted.
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
# Low-level frame tests (original)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_socket_send_receive(
    socket_pair: tuple[socket.socket, socket.socket],
    simple_scene: dict[str, object],
) -> None:
    """Send a scene over a socket pair and receive it on the other end."""
    client, server = socket_pair
    frame = encode_frame(simple_scene)
    client.sendall(frame)

    data = server.recv(4096)
    decoded, remaining = decode_frame(data)
    assert decoded == simple_scene
    assert remaining == b""


@pytest.mark.integration
def test_socket_multiple_messages(
    socket_pair: tuple[socket.socket, socket.socket],
    simple_scene: dict[str, object],
    interactive_scene: dict[str, object],
) -> None:
    """Multiple messages sent sequentially are correctly framed."""
    client, server = socket_pair

    frame1 = encode_frame(simple_scene)
    frame2 = encode_frame(interactive_scene)
    client.sendall(frame1 + frame2)

    data = b""
    while len(data) < len(frame1) + len(frame2):
        chunk = server.recv(4096)
        assert chunk, "Connection closed prematurely"
        data += chunk

    msg1, rest = decode_frame(data)
    msg2, rest = decode_frame(rest)
    assert msg1["id"] == "test-scene-001"
    assert msg2["id"] == "test-scene-002"
    assert rest == b""


@pytest.mark.integration
def test_socket_bidirectional(
    socket_pair: tuple[socket.socket, socket.socket],
) -> None:
    """Both sides of a socket pair can send and receive."""
    client, server = socket_pair

    # Client sends scene
    scene_msg: dict[str, object] = {"type": "scene", "id": "s1", "elements": []}
    client.sendall(encode_frame(scene_msg))

    # Server sends ack back
    ack_msg: dict[str, object] = {"type": "ack", "scene_id": "s1"}
    server.sendall(encode_frame(ack_msg))

    # Verify both sides received correctly
    server_data = server.recv(4096)
    client_data = client.recv(4096)

    received_scene, _ = decode_frame(server_data)
    received_ack, _ = decode_frame(client_data)

    assert received_scene["type"] == "scene"
    assert received_ack["type"] == "ack"


# ---------------------------------------------------------------------------
# Rapid scene updates — verify zero drops
# ---------------------------------------------------------------------------


class TestRapidSceneUpdates:
    """Send 100 scenes sequentially and verify each one is acked."""

    @pytest.mark.integration
    def test_bulk_scenes_zero_drops(self) -> None:
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        ack_count = 0

        def serve() -> None:
            nonlocal server_conn, ack_count
            server_conn = _mini_display_server(sock_path, ready_event)
            assert server_conn is not None
            for _ in range(NUM_RAPID_SCENES):
                msg = recv_message(server_conn, timeout=5)
                if msg is None:
                    break
                assert isinstance(msg, SceneMessage)
                send_message(
                    server_conn,
                    AckMessage(scene_id=msg.id, ts=time.time()),
                )
                ack_count += 1

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                acked_ids: list[str] = []
                for seq in range(NUM_RAPID_SCENES):
                    scene_id = f"s{seq}"
                    ack = client.show(
                        scene_id,
                        elements=[TextElement(id="t1", content=f"update-{seq}")],
                    )
                    assert ack is not None, f"Timeout on scene {seq}"
                    acked_ids.append(ack.scene_id)

                assert len(acked_ids) == NUM_RAPID_SCENES
                assert acked_ids == [f"s{i}" for i in range(NUM_RAPID_SCENES)]
        finally:
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)

        assert ack_count == NUM_RAPID_SCENES

    @pytest.mark.integration
    def test_bulk_scenes_rtt_under_threshold(self) -> None:
        """All 100 scene round-trips complete within 10s total."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display_server(sock_path, ready_event)
            assert server_conn is not None
            for _ in range(NUM_RAPID_SCENES):
                msg = recv_message(server_conn, timeout=5)
                if msg is None:
                    break
                assert isinstance(msg, SceneMessage)
                send_message(
                    server_conn,
                    AckMessage(scene_id=msg.id, ts=time.time()),
                )

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            t0 = time.monotonic()
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                for seq in range(NUM_RAPID_SCENES):
                    ack = client.show(
                        f"s{seq}",
                        elements=[TextElement(id="t1", content=f"update-{seq}")],
                    )
                    assert ack is not None
            elapsed = time.monotonic() - t0
            assert elapsed < 10.0, f"Took {elapsed:.2f}s for {NUM_RAPID_SCENES} scenes"
        finally:
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)


# ---------------------------------------------------------------------------
# Graceful disconnection
# ---------------------------------------------------------------------------


class TestGracefulDisconnection:
    """Verify clean shutdown when client or server disconnects."""

    @pytest.mark.integration
    def test_client_close_detected_by_server(self) -> None:
        """After client.close(), server recv returns None (EOF)."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        client_closed = threading.Event()
        server_saw_eof = False

        def serve() -> None:
            nonlocal server_conn, server_saw_eof
            server_conn = _mini_display_server(sock_path, ready_event)
            assert server_conn is not None
            client_closed.wait(timeout=5)
            # Use raw recv to distinguish EOF (b"") from timeout
            server_conn.settimeout(2.0)
            try:
                data = server_conn.recv(1)
            except TimeoutError:
                server_saw_eof = False
            else:
                server_saw_eof = data == b""

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            client = LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0)
            client.connect()
            assert client.is_connected
            client.close()
            closed = not client.is_connected
            assert closed
            client_closed.set()
            t.join(timeout=5)
            assert server_saw_eof
        finally:
            _cleanup(short_dir, server_conn)

    @pytest.mark.integration
    def test_server_close_client_recv_returns_none(self) -> None:
        """After server closes its socket, client.recv() returns None."""
        short_dir, sock_path = _short_sock_path()
        server_conn: socket.socket | None = None
        ready_event = threading.Event()
        client_connected = threading.Event()

        def serve() -> None:
            nonlocal server_conn
            server_conn = _mini_display_server(sock_path, ready_event)
            assert server_conn is not None
            # Wait for client to finish handshake before closing
            client_connected.wait(timeout=5)
            server_conn.close()
            server_conn = None

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        assert ready_event.wait(timeout=5)

        try:
            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client:
                client_connected.set()
                msg = client.recv(timeout=2.0)
                assert msg is None
        finally:
            _cleanup(short_dir, server_conn)
            t.join(timeout=5)


# ---------------------------------------------------------------------------
# Reconnection after server restart
# ---------------------------------------------------------------------------


class TestReconnection:
    """Verify a new client can connect after the first server stops."""

    @pytest.mark.integration
    def test_reconnect_after_server_restart(self) -> None:
        """A new LuxClient connects after the server restarts."""
        short_dir, sock_path = _short_sock_path()
        server_conn_1: socket.socket | None = None
        server_conn_2: socket.socket | None = None

        try:
            # --- Session 1: connect, exchange one scene, disconnect ---
            ready1 = threading.Event()

            def serve1() -> None:
                nonlocal server_conn_1
                server_conn_1 = _mini_display_server(sock_path, ready1)
                assert server_conn_1 is not None
                msg = recv_message(server_conn_1, timeout=5)
                assert isinstance(msg, SceneMessage)
                send_message(
                    server_conn_1,
                    AckMessage(scene_id=msg.id, ts=time.time()),
                )

            t1 = threading.Thread(target=serve1, daemon=True)
            t1.start()
            assert ready1.wait(timeout=5)

            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client1:
                ack = client1.show(
                    "s1",
                    elements=[TextElement(id="t1", content="first")],
                )
                assert ack is not None

            t1.join(timeout=5)
            if server_conn_1:
                server_conn_1.close()
                server_conn_1 = None

            # Remove old socket so new server can bind
            sock_path.unlink(missing_ok=True)

            # --- Session 2: new server, new client ---
            ready2 = threading.Event()

            def serve2() -> None:
                nonlocal server_conn_2
                server_conn_2 = _mini_display_server(sock_path, ready2)
                assert server_conn_2 is not None
                msg = recv_message(server_conn_2, timeout=5)
                assert isinstance(msg, SceneMessage)
                send_message(
                    server_conn_2,
                    AckMessage(scene_id=msg.id, ts=time.time()),
                )

            t2 = threading.Thread(target=serve2, daemon=True)
            t2.start()
            assert ready2.wait(timeout=5)

            with LuxClient(sock_path, auto_spawn=False, connect_timeout=2.0) as client2:
                ack = client2.show(
                    "s2",
                    elements=[TextElement(id="t1", content="second")],
                )
                assert ack is not None
                assert ack.scene_id == "s2"

            t2.join(timeout=5)
        finally:
            _cleanup(short_dir, server_conn_1, server_conn_2)
