"""Tests for LeafCertificate: hostname/SAN, expiry, PEM/disk persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.leaf_certificate import LeafCertificate

_HOSTNAME = "hub1.example.com"


def _signed_leaf(hostname: str = _HOSTNAME) -> LeafCertificate:
    ca = CertificateAuthority.create()
    csr = CertificateSigningRequest.generate(hostname, KeyPair.generate())
    return ca.sign_csr(csr)


def test_hostname_reads_back_the_san() -> None:
    leaf = _signed_leaf()
    assert leaf.hostname == _HOSTNAME


def test_is_expired_is_false_for_a_freshly_signed_leaf() -> None:
    leaf = _signed_leaf()
    assert leaf.is_expired() is False


def test_is_expired_as_of_is_true_past_not_valid_after() -> None:
    leaf = _signed_leaf()
    future = leaf.not_valid_after + timedelta(days=1)
    assert leaf.is_expired_as_of(future) is True


def test_not_valid_before_backdates_for_clock_skew() -> None:
    leaf = _signed_leaf()
    skew = datetime.now(UTC) - leaf.not_valid_before
    assert timedelta(minutes=4) < skew < timedelta(minutes=6)


def test_not_valid_after_is_about_one_year_out() -> None:
    leaf = _signed_leaf()
    delta = leaf.not_valid_after - datetime.now(UTC)
    assert timedelta(days=360) < delta < timedelta(days=370)


def test_pem_roundtrip_preserves_hostname() -> None:
    original = _signed_leaf()
    restored = LeafCertificate.from_pem(original.to_pem())
    assert restored.hostname == original.hostname


def test_der_roundtrip_preserves_hostname() -> None:
    # DER is the form ssl.SSLSocket.getpeercert(binary_form=True) returns --
    # this is the exact roundtrip the cross-host SAN check depends on.
    original = _signed_leaf()
    restored = LeafCertificate.from_der(original.to_der())
    assert restored.hostname == original.hostname


def test_der_roundtrip_preserves_the_whole_certificate() -> None:
    original = _signed_leaf()
    restored = LeafCertificate.from_der(original.to_der())
    assert restored.to_pem() == original.to_pem()


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "hub1.crt"
    original = _signed_leaf()
    original.save(path)
    restored = LeafCertificate.load(path)
    assert restored.hostname == original.hostname


def test_hostname_raises_when_san_is_absent() -> None:
    # Build a leaf with no SAN extension at all — outside this project's own
    # `CertificateAuthority.sign_csr`, which always adds one — to exercise
    # the boundary check directly.
    key_pair = KeyPair.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no-san")])
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
    leaf = LeafCertificate(key_pair.sign_certificate_builder(builder))
    with pytest.raises(ValueError, match="exactly one SAN DNSName"):
        _ = leaf.hostname
