"""TerminalConnection drains queued input before it closes."""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import pytest

from punt_lux.protocol.pty.frames import Frame, FrameDecoder, FrameKind
from punt_lux.terminal.connection import TerminalConnection

pytestmark = pytest.mark.integration


def _listener() -> tuple[socket.socket, Path]:
    path = Path(tempfile.mkdtemp(prefix="lux-")) / "pty.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    return server, path


def _received(peer: socket.socket) -> list[Frame]:
    peer.settimeout(1.0)
    decoder = FrameDecoder()
    frames: list[Frame] = []
    while data := peer.recv(65536):
        frames.extend(decoder.feed(data))
    return frames


def test_input_queued_before_close_reaches_the_daemon() -> None:
    server, path = _listener()
    connection = TerminalConnection(path)
    peer, _ = server.accept()
    keys = Frame(7, FrameKind.DATA, b"echo hi\r")
    connection.queue(keys)
    connection.drain(1.0)
    connection.close()
    assert keys in _received(peer)
    peer.close()
    server.close()


def test_drain_on_a_closed_connection_is_a_no_op() -> None:
    server, path = _listener()
    connection = TerminalConnection(path)
    connection.close()
    connection.drain(0.1)
    server.close()
