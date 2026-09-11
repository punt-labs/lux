"""CrossHostVerification -- Gate 2, the SAN/HubId hostname cross-check.

Unit tests drive real certificate material from ``punt_lux.trust`` (W7)
through a ``MagicMock(spec=ssl.SSLSocket)`` -- ``getpeercert(binary_form=True)``
is the one call this gate makes on the socket, so a spec'd mock is enough to
prove the DER-to-hostname-to-comparison path without a real TCP handshake.
``TestRealHandshake`` below additionally proves the same gate against a real
``ssl.SSLSocket`` produced by an actual mTLS handshake over TCP loopback,
mirroring ``test_cross_host_listener.py``'s own real-material approach.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from punt_lux.display.cross_host_listener import CrossHostListener
from punt_lux.display.cross_host_verification import CrossHostVerification
from punt_lux.domain.identity import HubId
from punt_lux.trust import CertificateAuthority, KeyPair, LeafCertificate


def _der_for(hostname: str) -> bytes:
    """Return DER bytes for a freshly-issued leaf naming *hostname*."""
    ca = CertificateAuthority.create()
    _, leaf = ca.issue_leaf(hostname)
    return leaf.to_der()


def _self_signed_builder(
    common_name: str,
) -> tuple[x509.CertificateBuilder, KeyPair]:
    """A bare, unsigned builder -- outside this project's own
    ``CertificateAuthority.sign_csr``, which always adds a SAN -- so a
    malformed-SAN leaf can be constructed directly for the boundary tests
    below.
    """
    key_pair = KeyPair.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key_pair.public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
    )
    return builder, key_pair


def _der_with_no_san() -> bytes:
    builder, key_pair = _self_signed_builder("no-san")
    leaf = LeafCertificate(key_pair.sign_certificate_builder(builder))
    return leaf.to_der()


def _der_with_two_sans() -> bytes:
    builder, key_pair = _self_signed_builder("two-san")
    builder = builder.add_extension(
        x509.SubjectAlternativeName(
            [x509.DNSName("a.example.com"), x509.DNSName("b.example.com")]
        ),
        critical=False,
    )
    leaf = LeafCertificate(key_pair.sign_certificate_builder(builder))
    return leaf.to_der()


def _ssl_sock(fd: int, der: bytes | None) -> MagicMock:
    """A ``MagicMock(spec=ssl.SSLSocket)`` -- passes ``isinstance`` checks
    against ``ssl.SSLSocket`` the way a real TLS-wrapped socket does."""
    sock = MagicMock(spec=ssl.SSLSocket)
    sock.fileno.return_value = fd
    sock.getpeercert.return_value = der
    return sock


def _plain_sock(fd: int) -> MagicMock:
    """A plain (non-TLS) socket mock -- the ``AF_UNIX`` shape, no ``spec``."""
    sock = MagicMock()
    sock.fileno.return_value = fd
    return sock


class TestSameHostBypass:
    """Invariant 4: the ``AF_UNIX`` leg's own trust argument stays untouched."""

    def test_a_plain_socket_is_never_rejected(self) -> None:
        verification = CrossHostVerification()
        sock = _plain_sock(10)

        rejected = verification.reject_unless_verified(sock, HubId("anything", 1))

        assert rejected is False
        sock.getpeercert.assert_not_called()


class TestMatching:
    def test_a_matching_hostname_is_not_rejected(self) -> None:
        verification = CrossHostVerification()
        der = _der_for("hub1.example.com")
        sock = _ssl_sock(10, der)

        rejected = verification.reject_unless_verified(
            sock, HubId("hub1.example.com", 123)
        )

        assert rejected is False

    def test_hostname_comparison_is_case_insensitive(self) -> None:
        # DNS names are case-insensitive (RFC 4343): the certificate's own
        # SAN casing must not matter against the self-reported HubId's.
        verification = CrossHostVerification()
        der = _der_for("Hub1.Example.com")
        sock = _ssl_sock(10, der)

        rejected = verification.reject_unless_verified(
            sock, HubId("hub1.example.com", 123)
        )

        assert rejected is False


class TestMismatch:
    def test_a_mismatched_hostname_is_rejected(self) -> None:
        verification = CrossHostVerification()
        der = _der_for("hub1.example.com")
        sock = _ssl_sock(10, der)

        rejected = verification.reject_unless_verified(
            sock, HubId("attacker.example.com", 999)
        )

        assert rejected is True

    def test_a_mismatch_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        verification = CrossHostVerification()
        der = _der_for("hub1.example.com")
        sock = _ssl_sock(10, der)

        with caplog.at_level("WARNING"):
            verification.reject_unless_verified(sock, HubId("attacker.example.com", 1))

        assert any("SAN/hub_id mismatch" in r.message for r in caplog.records)


class TestUnusableCertificate:
    """Fail-closed (Invariant 3): an unreadable cert is a rejection, not a crash."""

    def test_no_certificate_is_rejected(self) -> None:
        verification = CrossHostVerification()
        sock = _ssl_sock(10, None)

        rejected = verification.reject_unless_verified(sock, HubId("hub1", 1))

        assert rejected is True

    def test_a_certificate_with_no_san_is_rejected(self) -> None:
        verification = CrossHostVerification()
        sock = _ssl_sock(10, _der_with_no_san())

        rejected = verification.reject_unless_verified(sock, HubId("no-san", 1))

        assert rejected is True

    def test_a_certificate_with_two_sans_is_rejected(self) -> None:
        verification = CrossHostVerification()
        sock = _ssl_sock(10, _der_with_two_sans())

        rejected = verification.reject_unless_verified(sock, HubId("a.example.com", 1))

        assert rejected is True

    def test_an_unusable_certificate_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        verification = CrossHostVerification()
        sock = _ssl_sock(10, None)

        with caplog.at_level("WARNING"):
            verification.reject_unless_verified(sock, HubId("hub1", 1))

        assert any("peer certificate unusable" in r.message for r in caplog.records)

    def test_a_non_valueerror_parse_failure_is_still_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PY-EH-6: the DER a peer presents is adversary-influenced input
        parsed by a third-party library (cryptography/OpenSSL). Any parse
        failure -- not just the ``ValueError`` this project's own code
        happens to raise today -- must reject rather than propagate and
        crash the render loop."""

        def _raise_type_error(_der: bytes) -> LeafCertificate:
            msg = "simulated third-party parse failure"
            raise TypeError(msg)

        monkeypatch.setattr(
            "punt_lux.display.cross_host_verification.LeafCertificate.from_der",
            _raise_type_error,
        )
        verification = CrossHostVerification()
        sock = _ssl_sock(10, b"not-real-der")

        rejected = verification.reject_unless_verified(sock, HubId("hub1", 1))

        assert rejected is True


# ---------------------------------------------------------------------------
# Real handshake -- proves the gate against an actual ssl.SSLSocket, not just
# a spec'd mock. Helpers mirror test_cross_host_listener.py's own pattern.
# ---------------------------------------------------------------------------


def _server_context(ca: CertificateAuthority, tmp_path: Path) -> ssl.SSLContext:
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.CLIENT_AUTH)
    key_pair, leaf = ca.issue_leaf("display.example.com")
    cert_path, key_path = tmp_path / "server.crt", tmp_path / "server.key"
    cert_path.write_bytes(leaf.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _client_context(
    ca: CertificateAuthority,
    tmp_path: Path,
    leaf: tuple[KeyPair, LeafCertificate],
) -> ssl.SSLContext:
    context = ca.trust_anchor().build_ssl_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False  # loopback test host never matches a SAN
    key_pair, cert = leaf
    cert_path, key_path = tmp_path / "client.crt", tmp_path / "client.key"
    cert_path.write_bytes(cert.to_pem())
    key_path.write_bytes(key_pair.to_pem())
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def _connect_client(ctx: ssl.SSLContext, port: int) -> None:
    def _run() -> None:
        client = ctx.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        client.connect(("127.0.0.1", port))
        client.close()

    threading.Thread(target=_run, daemon=True).start()


def _accept_one(listener: CrossHostListener, *, rounds: int = 400) -> ssl.SSLSocket:
    for _ in range(rounds):
        listener.accept_pending()
        ready = listener.pump_ready()
        if ready:
            return ready[0]
        time.sleep(0.005)
    pytest.fail("no connection became ready before the round budget expired")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestRealHandshake:
    def test_a_real_peer_naming_its_own_host_is_accepted(self, tmp_path: Path) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        client_ctx = _client_context(ca, tmp_path, ca.issue_leaf("hub1.example.com"))
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            _connect_client(client_ctx, port)
            server_sock = _accept_one(listener)
            try:
                verification = CrossHostVerification()
                rejected = verification.reject_unless_verified(
                    server_sock, HubId("hub1.example.com", 1)
                )
                assert rejected is False
            finally:
                server_sock.close()
        finally:
            listener.shutdown()

    def test_a_real_peer_declaring_a_different_host_is_rejected(
        self, tmp_path: Path
    ) -> None:
        ca = CertificateAuthority.create()
        listener = CrossHostListener(_server_context(ca, tmp_path))
        # The client's cert genuinely names hub1 -- an honest mTLS handshake
        # -- but the ConnectMessage it would send declares a different host.
        client_ctx = _client_context(ca, tmp_path, ca.issue_leaf("hub1.example.com"))
        try:
            port = _free_port()
            listener.setup("127.0.0.1", port)
            _connect_client(client_ctx, port)
            server_sock = _accept_one(listener)
            try:
                verification = CrossHostVerification()
                rejected = verification.reject_unless_verified(
                    server_sock, HubId("attacker.example.com", 1)
                )
                assert rejected is True
            finally:
                server_sock.close()
        finally:
            listener.shutdown()
