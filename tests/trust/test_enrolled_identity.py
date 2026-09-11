"""Tests for EnrolledIdentity: the mTLS material an enrolled Hub holds."""

from __future__ import annotations

from pathlib import Path

import pytest

from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.enrolled_identity import EnrolledIdentity

_HOSTNAME = "hub1.example.com"


def _identity(hostname: str = _HOSTNAME) -> EnrolledIdentity:
    ca = CertificateAuthority.create()
    key_pair, leaf = ca.issue_leaf(hostname)
    return EnrolledIdentity(key_pair, leaf)


def test_constructor_rejects_a_mismatched_key_and_leaf() -> None:
    ca = CertificateAuthority.create()
    _key_pair_a, leaf_a = ca.issue_leaf(_HOSTNAME)
    key_pair_b, _leaf_b = ca.issue_leaf(_HOSTNAME)
    with pytest.raises(ValueError, match="does not match"):
        EnrolledIdentity(key_pair_b, leaf_a)


def test_load_rejects_a_swapped_key_and_certificate(tmp_path: Path) -> None:
    ca = CertificateAuthority.create()
    key_pair_a, _leaf_a = ca.issue_leaf("a.example.com")
    _key_pair_b, leaf_b = ca.issue_leaf("b.example.com")
    key_path = tmp_path / "swapped.key"
    cert_path = tmp_path / "swapped.crt"
    key_pair_a.save(key_path)
    leaf_b.save(cert_path)
    with pytest.raises(ValueError, match="does not match"):
        EnrolledIdentity.load(key_path, cert_path)


def test_hostname_reflects_the_leafs_hostname() -> None:
    identity = _identity()
    assert identity.hostname == _HOSTNAME


def test_key_pem_and_certificate_pem_are_pem_encoded() -> None:
    identity = _identity()
    assert identity.key_pem().startswith(b"-----BEGIN PRIVATE KEY-----")
    assert identity.certificate_pem().startswith(b"-----BEGIN CERTIFICATE-----")


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    key_path = tmp_path / "hub1.key"
    cert_path = tmp_path / "hub1.crt"
    original = _identity()
    original.save(key_path, cert_path)
    restored = EnrolledIdentity.load(key_path, cert_path)
    assert restored.hostname == original.hostname
    assert restored.certificate_pem() == original.certificate_pem()


def test_save_writes_the_key_as_0600(tmp_path: Path) -> None:
    import stat

    key_path = tmp_path / "hub1.key"
    _identity().save(key_path, tmp_path / "hub1.crt")
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
