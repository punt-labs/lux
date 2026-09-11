"""Tests for EnrollmentRequest: the Hub-side keypair+CSR half of enrollment."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.enrollment_request import EnrollmentRequest
from punt_lux.trust.leaf_certificate import LeafCertificate

_HOSTNAME = "hub1.example.com"


def test_generate_names_the_hostname_in_its_csr() -> None:
    request = EnrollmentRequest.generate(_HOSTNAME)
    assert request.csr.hostname == _HOSTNAME


def test_save_writes_the_key_as_0600_and_the_csr_readable(tmp_path: Path) -> None:
    import stat

    key_path = tmp_path / "hub1.key"
    csr_path = tmp_path / "hub1.csr"
    EnrollmentRequest.generate(_HOSTNAME).save(key_path, csr_path)
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert csr_path.exists()


def test_complete_pairs_the_requests_key_with_the_returned_leaf() -> None:
    request = EnrollmentRequest.generate(_HOSTNAME)
    ca = CertificateAuthority.create()
    leaf = ca.sign_csr(request.csr)
    identity = request.complete(leaf)
    assert identity.hostname == _HOSTNAME


def test_complete_rejects_a_leaf_for_a_different_key() -> None:
    request = EnrollmentRequest.generate(_HOSTNAME)
    ca = CertificateAuthority.create()
    # A leaf signed for a *different* enrollment request's key — simulates a
    # mismatched response (wrong file handed back during the offline CSR
    # exchange) rather than the one this request's key actually asked for.
    other_key_pair, other_leaf = ca.issue_leaf(_HOSTNAME)
    assert isinstance(other_leaf, LeafCertificate)
    with pytest.raises(ValueError, match="does not match"):
        request.complete(other_leaf)
    del other_key_pair
