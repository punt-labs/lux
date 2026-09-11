"""Tests for AwsPrivateCaProvider: trust anchor, issuance, protocol conformance.

The test double, ``_FakeAcmPcaClient``, signs behind a real
``CertificateAuthority`` internally — it stands in for AWS Private CA's
network calls, never for the cryptography. This proves the provider's own
plumbing (extracting bytes from the AWS response shape, splitting a
concatenated PEM chain, wiring a CSR into an issuance request) without
requiring live AWS credentials in CI (system.tex §"Provider 2 (Optional):
AWS Private CA (Managed)").
"""

from __future__ import annotations

import socket
import ssl
import threading
from pathlib import Path
from typing import Literal

import pytest
from cryptography import x509

from punt_lux.trust.aws_private_ca_config import AwsPrivateCaConfig
from punt_lux.trust.aws_private_ca_provider import AwsPrivateCaProvider
from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.provider import TrustAnchorProvider

_HOSTNAME = "hub1.example.com"
_CA_ARN = "arn:aws:acm-pca:us-east-1:123456789012:certificate-authority/abc-123"


class _FakeWaiter:
    """A no-op waiter — the fake client issues synchronously, so there is
    never a pending certificate to actually wait on.
    """

    def wait(self, **_kwargs: str) -> None:
        return None


class _FakeAcmPcaClient:
    """Stands in for ``boto3.client("acm-pca")``: real X.509 signing behind
    AWS's response shape, an intermediate above the root when requested,
    and a private map from issued ``CertificateArn`` back to its leaf.
    """

    def __init__(
        self,
        root: CertificateAuthority,
        intermediate: CertificateAuthority | None = None,
    ) -> None:
        self._root = root
        self._intermediate = intermediate
        self._signer = intermediate or root
        self._issued: dict[str, bytes] = {}
        self._next_arn = 0
        self.requested_waiter: str | None = None

    def issue_certificate(self, **kwargs: object) -> dict[str, str]:
        csr_pem = kwargs["Csr"]
        assert isinstance(csr_pem, bytes)
        csr = CertificateSigningRequest.from_pem(csr_pem)
        leaf = self._signer.sign_csr(csr)
        self._next_arn += 1
        arn = f"arn:aws:acm-pca:::certificate/fake-{self._next_arn}"
        self._issued[arn] = leaf.to_pem()
        return {"CertificateArn": arn}

    def get_certificate(self, **kwargs: str) -> dict[str, str]:
        arn = kwargs["CertificateArn"]
        return {"Certificate": self._issued[arn].decode("ascii")}

    def get_certificate_authority_certificate(self, **_kwargs: str) -> dict[str, str]:
        response = {"Certificate": self._signer.certificate_pem().decode("ascii")}
        if self._intermediate is not None:
            response["CertificateChain"] = self._root.certificate_pem().decode("ascii")
        return response

    def get_waiter(self, waiter_name: Literal["certificate_issued"]) -> _FakeWaiter:
        self.requested_waiter = waiter_name
        return _FakeWaiter()


def _provider(client: _FakeAcmPcaClient) -> AwsPrivateCaProvider:
    config = AwsPrivateCaConfig(
        ca_authority_arn=_CA_ARN, signing_algorithm="SHA256WITHECDSA"
    )
    return AwsPrivateCaProvider(config, client)


def test_satisfies_the_trust_anchor_provider_protocol() -> None:
    provider = _provider(_FakeAcmPcaClient(CertificateAuthority.create()))
    assert isinstance(provider, TrustAnchorProvider)


def test_trust_anchor_returns_the_root_certificate() -> None:
    root = CertificateAuthority.create()
    client = _FakeAcmPcaClient(root)
    provider = _provider(client)
    anchor = provider.trust_anchor()
    assert anchor.bundle_pem() == root.certificate_pem()


def test_trust_anchor_includes_the_intermediate_chain_when_present() -> None:
    root = CertificateAuthority.create()
    intermediate = CertificateAuthority.create()
    client = _FakeAcmPcaClient(root, intermediate)
    provider = _provider(client)
    anchor = provider.trust_anchor()
    certificates = x509.load_pem_x509_certificates(anchor.bundle_pem())
    subjects = {cert.subject for cert in certificates}
    intermediate_cert = x509.load_pem_x509_certificate(intermediate.certificate_pem())
    root_cert = x509.load_pem_x509_certificate(root.certificate_pem())
    assert subjects == {intermediate_cert.subject, root_cert.subject}


def test_issue_leaf_certificate_returns_a_leaf_naming_the_csr_hostname() -> None:
    client = _FakeAcmPcaClient(CertificateAuthority.create())
    provider = _provider(client)
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    leaf = provider.issue_leaf_certificate(csr)
    assert leaf.hostname == _HOSTNAME


def test_issue_leaf_certificate_waits_on_the_certificate_issued_waiter() -> None:
    client = _FakeAcmPcaClient(CertificateAuthority.create())
    provider = _provider(client)
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    provider.issue_leaf_certificate(csr)
    assert client.requested_waiter == "certificate_issued"


def test_issue_leaf_certificate_rejects_a_csr_with_a_tampered_signature() -> None:
    client = _FakeAcmPcaClient(CertificateAuthority.create())
    provider = _provider(client)
    key_pair = KeyPair.generate()
    csr = CertificateSigningRequest.generate(_HOSTNAME, key_pair)

    class _TamperedCsr:
        is_signature_valid = False
        hostname = _HOSTNAME
        subject = csr.subject
        public_key = csr.public_key

        def to_pem(self) -> bytes:
            return csr.to_pem()

    with pytest.raises(ValueError, match="signature does not verify"):
        provider.issue_leaf_certificate(_TamperedCsr())  # type: ignore[arg-type]


def test_issue_leaf_certificate_rejects_a_csr_missing_a_san(tmp_path: Path) -> None:
    client = _FakeAcmPcaClient(CertificateAuthority.create())
    provider = _provider(client)
    key_pair = KeyPair.generate()
    real_csr = CertificateSigningRequest.generate(_HOSTNAME, key_pair)

    class _NoSanCsr:
        is_signature_valid = True
        subject = real_csr.subject
        public_key = real_csr.public_key

        def to_pem(self) -> bytes:
            return real_csr.to_pem()

        @property
        def hostname(self) -> str:
            msg = "CSR must have exactly one SAN DNSName, found 0"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="SAN DNSName"):
        provider.issue_leaf_certificate(_NoSanCsr())  # type: ignore[arg-type]
    del tmp_path  # unused: signature kept symmetric with the sibling test


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


def test_aws_issued_material_completes_a_real_mtls_handshake(tmp_path: Path) -> None:
    """The scope this test can actually prove without live AWS: that a
    Provider-2-shaped leaf and trust anchor — extracted from AWS's own
    response fields the way this provider does it — chain and verify
    correctly under a real ``ssl.SSLContext``, including the
    AuthorityKeyIdentifier/SubjectKeyIdentifier pair RFC 5280 §4.2.1.1
    requires (system.tex). The signer behind the fake is a real
    ``CertificateAuthority``, which already sets both extensions
    (``certificate_authority.py``); this test does not, and cannot,
    verify ACM Private CA's own issued-certificate extensions.
    """
    root = CertificateAuthority.create()
    client = _FakeAcmPcaClient(root)
    provider = _provider(client)
    anchor = provider.trust_anchor()

    server_key = KeyPair.generate()
    server_csr = CertificateSigningRequest.generate("display.local", server_key)
    server_leaf = provider.issue_leaf_certificate(server_csr)

    client_key = KeyPair.generate()
    client_csr = CertificateSigningRequest.generate("hub1.local", client_key)
    client_leaf = provider.issue_leaf_certificate(client_csr)

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
            client_context.wrap_socket(raw, server_hostname="display.local") as tls,
        ):
            tls.sendall(b"hello")
            assert tls.recv(64) == b"hello"
    finally:
        server_thread.join(timeout=5.0)
        listener.close()

    assert result["outcome"] == "ok"
