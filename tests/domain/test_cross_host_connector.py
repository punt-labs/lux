"""CrossHostConnector / dial_cross_host -- the Hub's TCP+mTLS client leg (W10).

Drives a real ``ssl`` handshake over TCP loopback against a stand-in Display
server that speaks the genuine ``ReadyMessage``/``ConnectMessage`` wire
sequence -- OpenSSL's mutual verification is what actually proves the Hub
presents a trusted leaf and the connect handshake completes, exactly as a real
remote Display would meet the Hub's dial.
"""

from __future__ import annotations

import socket
import ssl
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.cross_host_connector import CrossHostConnector
from punt_lux.domain.hub.cross_host_link import dial_cross_host
from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.domain.hub_id import HubId
from punt_lux.protocol import ConnectMessage, ReadyMessage, recv_message, send_message
from punt_lux.trust import CertificateAuthority

if TYPE_CHECKING:
    from punt_lux.protocol import Message


def _display_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    """Server-side context: requires the Hub's client cert, presents its own."""
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("display.example.com")
    (tmp_path / "d.crt").write_bytes(leaf.to_pem())
    (tmp_path / "d.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "d.crt"), str(tmp_path / "d.key"))
    return ctx


def _hub_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    """Client-side context the Hub dials with: verifies the Display, presents
    its own leaf. ``check_hostname`` off -- loopback IP never matches a SAN."""
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    key_pair, leaf = ca.issue_leaf("hub1.example.com")
    (tmp_path / "h.crt").write_bytes(leaf.to_pem())
    (tmp_path / "h.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "h.crt"), str(tmp_path / "h.key"))
    return ctx


class _DisplayServer:
    """A stand-in remote Display: one TLS accept, ReadyMessage, capture Connect."""

    def __init__(self, ctx: ssl.SSLContext) -> None:
        self._ctx = ctx
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.bind(("127.0.0.1", 0))
        self._lsock.listen(1)
        self.port = int(self._lsock.getsockname()[1])
        self.received: list[Message] = []
        self._conns: list[ssl.SSLSocket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        try:
            raw, _ = self._lsock.accept()
            tls = self._ctx.wrap_socket(raw, server_side=True)
        except (OSError, ssl.SSLError):
            return
        self._conns.append(tls)
        send_message(tls, ReadyMessage())
        msg = recv_message(tls, timeout=5.0)
        if msg is not None:
            self.received.append(msg)

    def close(self) -> None:
        self._thread.join(timeout=5.0)
        for c in self._conns:
            c.close()
        self._lsock.close()


class TestCrossHostConnect:
    def test_a_trusted_hub_completes_the_handshake(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        connector = CrossHostConnector(
            host="127.0.0.1",
            port=server.port,
            ssl_context=_hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        try:
            result = connector.dial(connect_timeout=5.0)
            server.close()
            assert isinstance(result.ready, ReadyMessage)
            assert result.endpoint == f"127.0.0.1:{server.port}"
            assert len(server.received) == 1
            connect = server.received[0]
            assert isinstance(connect, ConnectMessage)
            assert connect.kind == "hub"  # never "test" cross-host (T6)
            assert connect.hub_id == HubId.current().wire_token
            result.sock.close()
        finally:
            server.close()

    def test_dial_cross_host_builds_a_connectable_display_link(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        link = dial_cross_host(
            "127.0.0.1",
            server.port,
            _hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        try:
            link.connect()
            assert link.is_connected
            server.close()
            assert isinstance(link.ready_message, ReadyMessage)
            assert [type(m).__name__ for m in server.received] == ["ConnectMessage"]
        finally:
            link.close()
            server.close()

    def test_an_untrusted_hub_certificate_is_rejected(self, tmp_path: Path) -> None:
        """A Hub whose leaf a different CA signed cannot complete the mTLS
        handshake -- dial fails loud, no half-open connection escapes."""
        ca = CertificateAuthority.create()
        other = CertificateAuthority.create()  # the Hub's leaf chains to this
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        connector = CrossHostConnector(
            host="127.0.0.1",
            port=server.port,
            ssl_context=_hub_context(other, tmp_path),
            name="lux-mcp",
        )
        try:
            with pytest.raises(DisplayNotConnectedError):
                connector.dial(connect_timeout=5.0)
            server.close()
            assert server.received == []  # no ConnectMessage ever accepted
        finally:
            server.close()

    def test_an_unreachable_endpoint_fails_loud(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = int(probe.getsockname()[1])  # closed once the with exits
        connector = CrossHostConnector(
            host="127.0.0.1",
            port=dead_port,
            ssl_context=_hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        with pytest.raises(DisplayNotConnectedError):
            connector.dial(connect_timeout=2.0)
