"""Tests for Pairing: the shared key/certificate public-key pairing check."""

from __future__ import annotations

import pytest
from cryptography import x509

from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.key_pairing import Pairing


def test_require_matching_passes_for_a_genuine_pair() -> None:
    key_pair, leaf = CertificateAuthority.create().issue_leaf("hub1.example.com")
    Pairing.require_matching(key_pair, leaf, "the leaf")  # must not raise


def test_require_matching_rejects_a_mismatched_pair() -> None:
    ca = CertificateAuthority.create()
    _key_a, leaf_a = ca.issue_leaf("a.example.com")
    key_b, _leaf_b = ca.issue_leaf("b.example.com")
    with pytest.raises(ValueError, match="does not match"):
        Pairing.require_matching(key_b, leaf_a, "the leaf")


def test_require_matching_pem_rejects_unequal_blobs() -> None:
    with pytest.raises(ValueError, match="does not match"):
        Pairing.require_matching_pem(b"a", b"b", "the certificate")


def test_require_matching_certificate_passes_for_a_genuine_pair() -> None:
    key_pair, leaf = CertificateAuthority.create().issue_leaf("hub1.example.com")
    raw_cert = x509.load_pem_x509_certificate(leaf.to_pem())
    Pairing.require_matching_certificate(key_pair, raw_cert, "the leaf")  # no raise


def test_require_matching_certificate_rejects_a_mismatched_pair() -> None:
    ca = CertificateAuthority.create()
    _key_a, leaf_a = ca.issue_leaf("a.example.com")
    key_b, _leaf_b = ca.issue_leaf("b.example.com")
    raw_cert_a = x509.load_pem_x509_certificate(leaf_a.to_pem())
    with pytest.raises(ValueError, match="does not match"):
        Pairing.require_matching_certificate(key_b, raw_cert_a, "the leaf")
