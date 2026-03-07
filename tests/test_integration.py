"""Integration tests: socket IPC, protocol framing.

These tests use real Unix domain sockets but no display process.
Run with: uv run pytest -m integration
"""

from __future__ import annotations

import socket

import pytest

from punt_lux import decode_frame, encode_frame


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
