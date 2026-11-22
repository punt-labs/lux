"""Identity resolution belongs to the display handshake, not construction."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from unittest.mock import patch

import pytest

from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.wire.model import (
    ConnectMessage,
    ReadyMessage,
    encode_frame,
    recv_message,
    send_message,
)
from punt_lux.wire.model.hub_id import HubId
from punt_lux.wire.model.messages.wire_vocabulary import CLIENT_VOCABULARY


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


class TestDisplayCompatibility:
    @pytest.mark.parametrize("version", ["0.1", "", "9.0", None])
    def test_an_incompatible_display_is_closed_before_identity_is_sent(
        self, version: str | None, caplog: pytest.LogCaptureFixture
    ) -> None:
        connector = HandshakeConnector(name="lux", kind="test")
        raw: dict[str, object] = {"type": "ready"}
        if version is not None:
            raw["version"] = version
        client, display = socket.socketpair()
        with client, display, patch.object(connector, "_connect_message") as identity:
            display.sendall(encode_frame(raw))
            with pytest.raises(DisplayNotConnectedError, match="Restart luxd-display"):
                connector.complete_handshake(client, "old-display", 1)
            identity.assert_not_called()
            assert client.fileno() == -1
            display.settimeout(1)
            assert display.recv(1) == b""
        assert "protocol 0.2" in caplog.text
        assert "make restart" in caplog.text
        assert "lux service restart" in caplog.text

    def test_the_current_display_is_accepted(self) -> None:
        connector = HandshakeConnector(name="lux", kind="test")
        client, display = socket.socketpair()
        with client, display:
            send_message(display, ReadyMessage())
            result = connector.complete_handshake(client, "new-display", 1)
            assert result.ready.version == "0.2"
            assert result.sock is client
            assert isinstance(
                recv_message(display, CLIENT_VOCABULARY, timeout=1), ConnectMessage
            )

    def test_reusing_an_old_display_reports_the_restart_instead_of_spawning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with TemporaryDirectory(prefix="lux-") as base:
            path = Path(base) / "d.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path))
                listener.listen()
                listener.settimeout(5)

                def serve_probe_and_handshake() -> list[bytes]:
                    replies: list[bytes] = []
                    for _ in range(2):
                        peer, _address = listener.accept()
                        with peer:
                            peer.settimeout(5)
                            send_message(peer, ReadyMessage(version="0.1"))
                            replies.append(peer.recv(1))
                    return replies

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(serve_probe_and_handshake)
                    connector = HandshakeConnector(
                        name="lux", kind="test", socket_path=path
                    )
                    with (
                        patch(
                            "punt_lux.service.display_paths.DisplayPaths._spawn",
                            side_effect=AssertionError("must reuse the live Display"),
                        ),
                        pytest.raises(
                            DisplayNotConnectedError, match="Restart luxd-display"
                        ),
                    ):
                        connector.dial(1)
                    assert future.result(timeout=5) == [b"", b""]
        assert "Restart luxd-display" in caplog.text
