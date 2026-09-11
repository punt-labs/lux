"""CrossHostConnector / CrossHostEndpoint -- the Hub's TCP+mTLS client leg (W10).

Drives a real ``ssl`` handshake over TCP loopback against a stand-in Display
server that speaks the genuine ``ReadyMessage``/``ConnectMessage`` wire
sequence -- OpenSSL's mutual verification is what actually proves the Hub
presents a trusted leaf and the connect handshake completes, exactly as a real
remote Display would meet the Hub's dial. The Hub dials ``host="localhost"``
against a certificate whose SAN is ``localhost`` so ``check_hostname`` (now
mandatory) verifies over loopback.
"""

from __future__ import annotations

import socket
import ssl
import struct
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.cross_host_connector import CrossHostConnector
from punt_lux.domain.hub.cross_host_link import CrossHostEndpoint
from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.domain.hub_id import HubId
from punt_lux.protocol import ConnectMessage, ReadyMessage, recv_message, send_message
from punt_lux.trust import CertificateAuthority

if TYPE_CHECKING:
    from punt_lux.protocol import Message


def _display_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    """Server-side context: requires the Hub's client cert, presents its own.

    The leaf SAN is ``localhost`` so a Hub dialing ``host="localhost"`` with
    ``check_hostname=True`` matches it over the loopback interface.
    """
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("localhost")
    (tmp_path / "d.crt").write_bytes(leaf.to_pem())
    (tmp_path / "d.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "d.crt"), str(tmp_path / "d.key"))
    return ctx


def _hub_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    """Client-side context the Hub dials with: verifies the Display's leaf
    (``check_hostname`` + ``CERT_REQUIRED``, both mandatory) and presents its own."""
    ctx = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    key_pair, leaf = ca.issue_leaf("hub1.example.com")
    (tmp_path / "h.crt").write_bytes(leaf.to_pem())
    (tmp_path / "h.key").write_bytes(key_pair.to_pem())
    ctx.load_cert_chain(str(tmp_path / "h.crt"), str(tmp_path / "h.key"))
    return ctx


class _DisplayServer:
    """A stand-in remote Display: one TLS accept, ReadyMessage, capture Connect."""

    def __init__(self, ctx: ssl.SSLContext, bind_host: str = "127.0.0.1") -> None:
        family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
        self._ctx = ctx
        self._lsock = socket.socket(family, socket.SOCK_STREAM)
        self._lsock.bind((bind_host, 0))
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


def _ipv6_loopback_available() -> bool:
    """Return whether ``::1`` can be bound -- CI runners without IPv6 skip."""
    if not socket.has_ipv6:
        return False
    probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        probe.bind(("::1", 0))
    except OSError:
        return False
    finally:
        probe.close()
    return True


class TestVerificationGuard:
    """DES-090 boundary: the dialer refuses a context that skips verification,
    so MITM protection is structural, not a property of the call site."""

    def test_a_context_without_check_hostname_is_refused(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        ctx = _hub_context(ca, tmp_path)
        ctx.check_hostname = False
        with pytest.raises(ValueError, match="check_hostname"):
            CrossHostConnector(host="localhost", port=1, ssl_context=ctx, name="h")

    def test_a_context_that_skips_peer_verification_is_refused(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        ctx = _hub_context(ca, tmp_path)
        ctx.check_hostname = False  # required before verify_mode may be lowered
        ctx.verify_mode = ssl.CERT_NONE
        with pytest.raises(ValueError, match="CERT_REQUIRED"):
            CrossHostConnector(host="localhost", port=1, ssl_context=ctx, name="h")


class TestCrossHostConnect:
    def test_a_trusted_hub_completes_the_handshake(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        connector = CrossHostConnector(
            host="localhost",
            port=server.port,
            ssl_context=_hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        try:
            result = connector.dial(connect_timeout=5.0)
            server.close()
            assert isinstance(result.ready, ReadyMessage)
            assert result.endpoint == f"localhost:{server.port}"
            assert len(server.received) == 1
            connect = server.received[0]
            assert isinstance(connect, ConnectMessage)
            assert connect.kind == "hub"  # never "test" cross-host (T6)
            assert connect.hub_id == HubId.current().wire_token
            result.sock.close()
        finally:
            server.close()

    def test_the_dialed_socket_carries_a_send_timeout(self, tmp_path: Path) -> None:
        """A stalled Display must not wedge the Hub's sends: SO_SNDTIMEO is set
        on the connected socket, exactly as the AF_UNIX leg bounds its sends."""
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        connector = CrossHostConnector(
            host="localhost",
            port=server.port,
            ssl_context=_hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        try:
            result = connector.dial(connect_timeout=5.0)
            server.close()
            raw = result.sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, 16)
            seconds, _micros = struct.unpack("ll", raw)
            assert seconds > 0  # a real send-timeout ceiling, not the default 0
            result.sock.close()
        finally:
            server.close()

    def test_dial_cross_host_builds_a_connectable_display_link(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        link = CrossHostEndpoint(
            "localhost", server.port, _hub_context(ca, tmp_path)
        ).dial(name="lux-mcp")
        try:
            link.connect()
            assert link.is_connected
            server.close()
            assert isinstance(link.ready_message, ReadyMessage)
            assert [type(m).__name__ for m in server.received] == ["ConnectMessage"]
        finally:
            link.close()
            server.close()

    @pytest.mark.skipif(
        not _ipv6_loopback_available(), reason="no IPv6 loopback on this host"
    )
    def test_an_ipv6_display_is_reachable(self, tmp_path: Path) -> None:
        """getaddrinfo/AF_UNSPEC lets the Hub dial an IPv6-only Display. The
        server binds ``::1`` only, so the connection succeeds solely because the
        dialer tries the ``::1`` address ``localhost`` resolves to."""
        ca = CertificateAuthority.create()
        server = _DisplayServer(_display_context(ca, tmp_path), bind_host="::1")
        server.start()
        connector = CrossHostConnector(
            host="localhost",
            port=server.port,
            ssl_context=_hub_context(ca, tmp_path),
            name="lux-mcp",
        )
        try:
            result = connector.dial(connect_timeout=5.0)
            server.close()
            assert isinstance(result.ready, ReadyMessage)
            assert len(server.received) == 1
            result.sock.close()
        finally:
            server.close()


class TestCrossHostFailure:
    def test_an_untrusted_hub_certificate_is_rejected(self, tmp_path: Path) -> None:
        """A Hub whose leaf a different CA signed cannot complete the mTLS
        handshake -- dial fails loud, no half-open connection escapes."""
        ca = CertificateAuthority.create()
        other = CertificateAuthority.create()  # the Hub's leaf chains to this
        server = _DisplayServer(_display_context(ca, tmp_path))
        server.start()
        connector = CrossHostConnector(
            host="localhost",
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

    def test_a_failed_dial_leaks_no_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every socket the dialer opens is closed before dial raises -- a
        failed handshake or connect must not leak an fd."""
        opened: list[socket.socket] = []
        real_socket = socket.socket

        def _tracking_socket(*args: int) -> socket.socket:
            sock = real_socket(*args)
            opened.append(sock)
            return sock

        monkeypatch.setattr(
            "punt_lux.domain.hub.cross_host_connector.socket.socket", _tracking_socket
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = int(probe.getsockname()[1])
        connector = CrossHostConnector(
            host="127.0.0.1",
            port=dead_port,
            ssl_context=_hub_context(ca := CertificateAuthority.create(), tmp_path),
            name="lux-mcp",
        )
        assert ca is not None
        with pytest.raises(DisplayNotConnectedError):
            connector.dial(connect_timeout=2.0)
        assert opened, "the dialer opened at least one socket"
        assert all(s.fileno() == -1 for s in opened)  # every one was closed
