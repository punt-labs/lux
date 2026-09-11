"""Tests for CertificateAuthority: root creation, save/load, CSR signing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from punt_lux.trust.ca_paths import CaPaths
from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair

_HOSTNAME = "hub1.example.com"


def test_create_produces_a_root_valid_for_about_ten_years() -> None:
    ca = CertificateAuthority.create()
    from cryptography import x509

    # Round-trip through PEM to read the root's own not-valid-after, since
    # CertificateAuthority does not expose it directly (only leaves do).
    root = x509.load_pem_x509_certificate(ca.certificate_pem())
    delta = root.not_valid_after_utc - datetime.now(UTC)
    assert timedelta(days=3640) < delta < timedelta(days=3660)


def test_save_then_load_preserves_the_root(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    original = CertificateAuthority.create()
    original.save(paths)
    restored = CertificateAuthority.load(paths)
    assert restored.certificate_pem() == original.certificate_pem()


def test_save_writes_the_key_as_0600(tmp_path: Path) -> None:
    import stat

    paths = CaPaths(tmp_path)
    CertificateAuthority.create().save(paths)
    mode = stat.S_IMODE(paths.root_key_path.stat().st_mode)
    assert mode == 0o600


def test_save_creates_the_directory_as_0700(tmp_path: Path) -> None:
    import stat

    paths = CaPaths(tmp_path / "ca")
    CertificateAuthority.create().save(paths)
    mode = stat.S_IMODE(paths.dir.stat().st_mode)
    assert mode == 0o700


def test_trust_anchor_bundle_contains_the_root_pem() -> None:
    ca = CertificateAuthority.create()
    anchor = ca.trust_anchor()
    assert anchor.bundle_pem() == ca.certificate_pem()


def test_sign_csr_produces_a_leaf_naming_the_csr_hostname() -> None:
    ca = CertificateAuthority.create()
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    leaf = ca.sign_csr(csr)
    assert leaf.hostname == _HOSTNAME


def test_sign_csr_produces_a_leaf_issued_by_this_ca() -> None:
    from cryptography import x509

    ca = CertificateAuthority.create()
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    leaf = ca.sign_csr(csr)
    leaf_cert = x509.load_pem_x509_certificate(leaf.to_pem())
    root_cert = x509.load_pem_x509_certificate(ca.certificate_pem())
    assert leaf_cert.issuer == root_cert.subject


def test_sign_csr_produces_a_leaf_valid_for_about_one_year() -> None:
    ca = CertificateAuthority.create()
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    leaf = ca.sign_csr(csr)
    delta = leaf.not_valid_after - datetime.now(UTC)
    assert timedelta(days=360) < delta < timedelta(days=370)


def test_sign_csr_binds_the_csrs_own_public_key() -> None:
    ca = CertificateAuthority.create()
    key_pair = KeyPair.generate()
    csr = CertificateSigningRequest.generate(_HOSTNAME, key_pair)
    leaf = ca.sign_csr(csr)
    assert leaf.public_key_pem() == key_pair.public_key_pem()


def test_sign_csr_rejects_a_csr_with_a_tampered_signature() -> None:
    ca = CertificateAuthority.create()
    # Sign under one key, then rebind the CSR's declared public key to a
    # different one — the self-signature no longer verifies against the
    # (now-mismatched) declared key, exactly the forgery this check exists
    # to catch: a CSR claiming a public key its signer never held.
    key_pair = KeyPair.generate()
    csr = CertificateSigningRequest.generate(_HOSTNAME, key_pair)

    class _TamperedCsr:
        is_signature_valid = False
        hostname = _HOSTNAME
        subject = csr.subject
        public_key = csr.public_key

    with pytest.raises(ValueError, match="signature does not verify"):
        ca.sign_csr(_TamperedCsr())  # type: ignore[arg-type]


def test_issue_leaf_returns_a_matching_keypair_and_leaf() -> None:
    ca = CertificateAuthority.create()
    key_pair, leaf = ca.issue_leaf(_HOSTNAME)
    assert leaf.hostname == _HOSTNAME
    assert leaf.public_key_pem() == key_pair.public_key_pem()
