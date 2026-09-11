"""Tests for TrustAnchor: PEM bundling and real stdlib-``ssl`` verification.

The loopback mTLS tests are the "does this material actually work"
proof — they drive real ``ssl.SSLSocket`` handshakes over TCP loopback
using the exact ``ssl.SSLContext`` construction W8's cross-host listener
will use, without building W8's non-blocking accept loop itself. Two
verified outcomes: a leaf from the trust anchor's own CA is accepted, and
a leaf from an unrelated CA — an unenrolled machine — is rejected at the
handshake before any application byte crosses (system.tex T1/Invariant 3).
"""

from __future__ import annotations

import socket
import ssl
import threading
from pathlib import Path

import pytest

from punt_lux.trust.certificate_authority import CertificateAuthority

_SERVER_HOSTNAME = "display.local"
_CLIENT_HOSTNAME = "hub1.local"


def test_bundle_pem_concatenates_every_certificate() -> None:
    ca = CertificateAuthority.create()
    anchor = ca.trust_anchor()
    assert anchor.bundle_pem() == ca.certificate_pem()


def test_construction_rejects_an_empty_certificate_set() -> None:
    from punt_lux.trust.trust_anchor import TrustAnchor

    with pytest.raises(ValueError, match="at least one certificate"):
        TrustAnchor(())


def _write_identity(
    directory: Path, name: str, key_pem: bytes, cert_pem: bytes
) -> tuple[str, str]:
    key_path = directory / f"{name}.key"
    cert_path = directory / f"{name}.crt"
    key_path.write_bytes(key_pem)
    cert_path.write_bytes(cert_pem)
    return str(key_path), str(cert_path)


def _serve_once(
    server_socket: socket.socket, context: ssl.SSLContext, result: dict[str, str]
) -> None:
    """Accept one connection, complete the handshake, and record the outcome."""
    raw, _addr = server_socket.accept()
    try:
        with context.wrap_socket(raw, server_side=True) as tls:
            tls.settimeout(5.0)
            data = tls.recv(64)
            tls.sendall(data)
        result["outcome"] = "ok"
    except ssl.SSLError as exc:
        result["outcome"] = "rejected"
        result["error"] = str(exc)
    finally:
        raw.close()


def test_a_leaf_from_the_trust_anchors_own_ca_completes_the_handshake(
    tmp_path: Path,
) -> None:
    ca = CertificateAuthority.create()
    anchor = ca.trust_anchor()
    server_key, server_leaf = ca.issue_leaf(_SERVER_HOSTNAME)
    client_key, client_leaf = ca.issue_leaf(_CLIENT_HOSTNAME)

    server_key_path, server_cert_path = _write_identity(
        tmp_path, "server", server_key.to_pem(), server_leaf.to_pem()
    )
    client_key_path, client_cert_path = _write_identity(
        tmp_path, "client", client_key.to_pem(), client_leaf.to_pem()
    )

    server_context = anchor.build_ssl_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(server_cert_path, server_key_path)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    result: dict[str, str] = {}
    server_thread = threading.Thread(
        target=_serve_once, args=(listener, server_context, result)
    )
    server_thread.start()
    try:
        client_context = anchor.build_ssl_context(ssl.Purpose.SERVER_AUTH)
        client_context.load_cert_chain(client_cert_path, client_key_path)
        with (
            socket.create_connection((host, port), timeout=5.0) as raw,
            client_context.wrap_socket(raw, server_hostname=_SERVER_HOSTNAME) as tls,
        ):
            tls.sendall(b"hello")
            assert tls.recv(64) == b"hello"
    finally:
        server_thread.join(timeout=5.0)
        listener.close()

    assert result["outcome"] == "ok"


def test_a_leaf_from_an_unrelated_ca_is_rejected_at_the_handshake(
    tmp_path: Path,
) -> None:
    # Two independent CAs — the server trusts only the first. The second
    # CA's leaf, naming the identical hostname, is what an unenrolled
    # machine presents: syntactically valid, but not signed by the anchor.
    trusted_ca = CertificateAuthority.create()
    other_ca = CertificateAuthority.create()
    anchor = trusted_ca.trust_anchor()

    server_key, server_leaf = trusted_ca.issue_leaf(_SERVER_HOSTNAME)
    unenrolled_key, unenrolled_leaf = other_ca.issue_leaf(_CLIENT_HOSTNAME)

    server_key_path, server_cert_path = _write_identity(
        tmp_path, "server", server_key.to_pem(), server_leaf.to_pem()
    )
    client_key_path, client_cert_path = _write_identity(
        tmp_path, "unenrolled", unenrolled_key.to_pem(), unenrolled_leaf.to_pem()
    )

    server_context = anchor.build_ssl_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(server_cert_path, server_key_path)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()

    result: dict[str, str] = {}
    server_thread = threading.Thread(
        target=_serve_once, args=(listener, server_context, result)
    )
    server_thread.start()
    try:
        client_context = anchor.build_ssl_context(ssl.Purpose.SERVER_AUTH)
        client_context.load_cert_chain(client_cert_path, client_key_path)
        # Under TLS 1.3, client-certificate authentication happens
        # *post*-handshake: ``wrap_socket()`` can return successfully even
        # though the server is about to reject the client's certificate —
        # the server's rejection alert only arrives, and only then raises,
        # on the next read. Asserting on ``wrap_socket()`` alone would pass
        # for the wrong reason; driving one round of I/O is what actually
        # exercises the rejection this test exists to prove (system.tex
        # T1: "no application byte is ever read from it").
        with (
            pytest.raises(ssl.SSLError),
            socket.create_connection((host, port), timeout=5.0) as raw,
            client_context.wrap_socket(raw, server_hostname=_SERVER_HOSTNAME) as tls,
        ):
            tls.sendall(b"hello")
            tls.recv(64)
    finally:
        server_thread.join(timeout=5.0)
        listener.close()

    assert result["outcome"] == "rejected"
