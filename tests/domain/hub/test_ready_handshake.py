"""The Ready boundary closes failed connections and names incompatible peers."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.domain.hub.ready_handshake import ReadyHandshake
from punt_lux.wire.model import ReadyMessage, send_message


class TestReadyHandshake:
    def test_a_current_ready_keeps_the_socket_open(self) -> None:
        client, display = socket.socketpair()
        with client, display:
            send_message(display, ReadyMessage())
            ready = ReadyHandshake.receive(client, "current-display", 1)
            assert ready.version == "0.2"
            assert client.fileno() != -1

    def test_an_empty_handshake_closes_the_socket(self) -> None:
        client, display = socket.socketpair()
        with (
            client,
            display,
            patch(
                "punt_lux.domain.hub.ready_handshake.recv_message", return_value=None
            ),
        ):
            with pytest.raises(DisplayNotConnectedError, match="Handshake timed out"):
                ReadyHandshake.receive(client, "silent-display", 1)
            assert client.fileno() == -1

    def test_an_old_display_logs_an_error_with_the_restart_action(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client, display = socket.socketpair()
        with client, display:
            send_message(display, ReadyMessage(version="0.1"))
            with pytest.raises(DisplayNotConnectedError, match="Restart luxd-display"):
                ReadyHandshake.receive(client, "old-display", 1)
            assert client.fileno() == -1
        assert any(
            r.levelname == "ERROR" and "make restart" in r.message
            for r in caplog.records
        )
