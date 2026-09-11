"""Unit tests for HandshakeResult and the re-exported DisplayNotConnectedError."""

from __future__ import annotations

import socket

from punt_lux.domain.hub.handshake_outcome import (
    DisplayNotConnectedError,
    HandshakeResult,
)
from punt_lux.protocol import ReadyMessage


def test_handshake_result_carries_the_endpoint_and_ready_message() -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        ready = ReadyMessage(version="1")
        result = HandshakeResult(sock=sock, endpoint="/tmp/lux.sock", ready=ready)
        assert result.sock is sock
        assert result.endpoint == "/tmp/lux.sock"
        assert result.ready is ready
    finally:
        sock.close()


def test_display_not_connected_error_is_re_exported_from_its_own_module() -> None:
    from punt_lux.domain.hub.display_not_connected import (
        DisplayNotConnectedError as Original,
    )

    assert DisplayNotConnectedError is Original
