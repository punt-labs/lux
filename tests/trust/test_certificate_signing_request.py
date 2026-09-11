"""Tests for CertificateSigningRequest: generation, hostname/SAN, validity."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair

_HOSTNAME = "hub1.example.com"


def test_generate_names_the_hostname_as_san() -> None:
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    assert csr.hostname == _HOSTNAME


def test_generate_produces_a_self_verifying_signature() -> None:
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    assert csr.is_signature_valid is True


def test_generate_binds_the_supplied_public_key() -> None:
    key_pair = KeyPair.generate()
    csr = CertificateSigningRequest.generate(_HOSTNAME, key_pair)
    assert csr.public_key.public_numbers() == key_pair.public_key.public_numbers()


def test_pem_roundtrip_preserves_hostname_and_signature() -> None:
    original = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    restored = CertificateSigningRequest.from_pem(original.to_pem())
    assert restored.hostname == _HOSTNAME
    assert restored.is_signature_valid is True


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "hub1.csr"
    original = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    original.save(path)
    restored = CertificateSigningRequest.load(path)
    assert restored.hostname == original.hostname


def test_hostname_raises_when_san_is_absent() -> None:
    # Build a CSR with no SAN extension at all — outside this class's own
    # `generate()`, which always adds one, to exercise the boundary check.
    key_pair = KeyPair.generate()
    builder = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no-san")])
    )
    csr = CertificateSigningRequest(key_pair.sign_csr_builder(builder))
    with pytest.raises(ValueError, match="exactly one SAN DNSName"):
        _ = csr.hostname


def test_hostname_raises_when_san_names_more_than_one_host() -> None:
    key_pair = KeyPair.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "multi")])
    builder = x509.CertificateSigningRequestBuilder().subject_name(name)
    builder = builder.add_extension(
        x509.SubjectAlternativeName(
            [x509.DNSName("a.example.com"), x509.DNSName("b.example.com")]
        ),
        critical=False,
    )
    csr = CertificateSigningRequest(key_pair.sign_csr_builder(builder))
    with pytest.raises(ValueError, match="exactly one SAN DNSName"):
        _ = csr.hostname
