"""Tests for PersonalCaProvider: bootstrap, trust anchor, issuance, own leaf."""

from __future__ import annotations

from pathlib import Path

from punt_lux.trust.ca_paths import CaPaths
from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.personal_ca_provider import PersonalCaProvider

_HOSTNAME = "hub1.example.com"


def test_bootstrap_creates_a_ca_when_none_exists(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    assert paths.exists() is False
    PersonalCaProvider.bootstrap(paths)
    assert paths.exists() is True


def test_bootstrap_loads_the_existing_ca_on_a_second_call(tmp_path: Path) -> None:
    paths = CaPaths(tmp_path)
    first = PersonalCaProvider.bootstrap(paths)
    second = PersonalCaProvider.bootstrap(paths)
    assert first.trust_anchor().bundle_pem() == second.trust_anchor().bundle_pem()


def test_trust_anchor_matches_the_underlying_ca() -> None:
    ca = CertificateAuthority.create()
    provider = PersonalCaProvider(ca)
    assert provider.trust_anchor().bundle_pem() == ca.certificate_pem()


def test_issue_leaf_certificate_signs_with_the_underlying_ca() -> None:
    ca = CertificateAuthority.create()
    provider = PersonalCaProvider(ca)
    csr = CertificateSigningRequest.generate(_HOSTNAME, KeyPair.generate())
    leaf = provider.issue_leaf_certificate(csr)
    assert leaf.hostname == _HOSTNAME


def test_issue_own_leaf_returns_an_identity_naming_the_hostname() -> None:
    provider = PersonalCaProvider(CertificateAuthority.create())
    identity = provider.issue_own_leaf(_HOSTNAME)
    assert identity.hostname == _HOSTNAME
