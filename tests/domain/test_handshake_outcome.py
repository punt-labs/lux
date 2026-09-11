"""Unit tests for HandshakeResult and the re-exported DisplayNotConnectedError."""

from __future__ import annotations

import socket
from pathlib import Path

from punt_lux.domain.hub.handshake_outcome import (
    DisplayNotConnectedError,
    HandshakeResult,
)
from punt_lux.protocol import ReadyMessage


def test_handshake_result_carries_the_socket_path_and_ready_message() -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        ready = ReadyMessage(version="1")
        path = Path("/tmp/lux.sock")
        result = HandshakeResult(sock=sock, socket_path=path, ready=ready)
        assert result.sock is sock
        assert result.socket_path == path
        assert result.ready is ready
    finally:
        sock.close()


def test_display_not_connected_error_is_re_exported_from_its_own_module() -> None:
    from punt_lux.domain.hub.display_not_connected import (
        DisplayNotConnectedError as Original,
    )

    assert DisplayNotConnectedError is Original
