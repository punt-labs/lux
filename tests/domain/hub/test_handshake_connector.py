"""Identity resolution belongs to the display handshake, not construction."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from typing import Literal
from unittest.mock import patch

import pytest

from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.domain.hub_id import HubId
from punt_lux.protocol import ConnectMessage, ReadyMessage, recv_message, send_message
from punt_lux.protocol.messages.wire_vocabulary import CLIENT_VOCABULARY


class TestLazyHubIdentity:
    def test_importing_hub_and_building_replicator_does_not_resolve_dns(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from unittest.mock import patch\n"
                    "with patch('socket.getfqdn', "
                    "side_effect=AssertionError('DNS')) as dns:\n"
                    " import punt_lux.luxd\n"
                    " from punt_lux.domain.hub.replicator_instance "
                    "import hub_replicator\n"
                    " assert hub_replicator is not None\n"
                    " dns.assert_not_called()\n"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("kind", ["hub", "test"])
    def test_handshake_resolves_once_and_keeps_identity(
        self, kind: Literal["hub", "test"]
    ) -> None:
        with patch("socket.getfqdn", return_value="Hub.Example.com") as dns:
            connector = HandshakeConnector(name="lux", kind=kind)
            dns.assert_not_called()
            expected = (
                HubId("Hub.Example.com", os.getpid()) if kind == "hub" else HubId.stub()
            )
            for _ in range(2):
                client, display = socket.socketpair()
                with client, display:
                    send_message(display, ReadyMessage())
                    connector.complete_handshake(client, "test", 1)
                    message = recv_message(display, CLIENT_VOCABULARY, timeout=1)
                    assert isinstance(message, ConnectMessage)
                    assert message.hub_id == expected.wire_token
            assert dns.call_count == (1 if kind == "hub" else 0)

    def test_an_unnamed_handshake_does_not_resolve_dns(self) -> None:
        with patch("socket.getfqdn", side_effect=AssertionError("DNS")) as dns:
            connector = HandshakeConnector(name=None, kind="hub")
            client, display = socket.socketpair()
            with client, display:
                send_message(display, ReadyMessage())
                connector.complete_handshake(client, "test", 1)
            dns.assert_not_called()

    def test_a_failed_handshake_does_not_resolve_dns(self) -> None:
        with patch("socket.getfqdn", side_effect=AssertionError("DNS")) as dns:
            connector = HandshakeConnector(name="lux", kind="hub")
            client, display = socket.socketpair()
            with client, display:
                display.close()
                with pytest.raises(DisplayNotConnectedError):
                    connector.complete_handshake(client, "test", 1)
            dns.assert_not_called()

    @pytest.mark.parametrize("fqdn", ["münchen.example", "hub.例"])
    def test_an_invalid_identity_closes_the_socket_and_wraps_the_error(
        self, fqdn: str
    ) -> None:
        with patch("socket.getfqdn", return_value=fqdn):
            connector = HandshakeConnector(name="lux", kind="hub")
            client, display = socket.socketpair()
            with client, display:
                send_message(display, ReadyMessage())
                with pytest.raises(DisplayNotConnectedError) as caught:
                    connector.complete_handshake(client, "test", 1)
                assert isinstance(caught.value.__cause__, ValueError)
                assert client.fileno() == -1
                display.settimeout(1)
                assert display.recv(1) == b""
