"""Tests for PersonalCaProvider: bootstrap, trust anchor, issuance, own leaf."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_bootstrap_discards_its_own_ca_when_it_loses_the_rename_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent bootstrap's rename already won by the time this one
    would run its own — this process must load the winner's CA, not its
    own, and must not leave its discarded staging directory behind.
    """
    paths = CaPaths(tmp_path / "ca")
    winner = CertificateAuthority.create()
    winner.save(paths)

    def _not_yet(_self: CaPaths) -> bool:
        return False

    def _lose_the_race(_self: Path, _target: str | Path) -> Path:
        raise OSError("simulated race loss")

    monkeypatch.setattr(CaPaths, "exists", _not_yet)
    monkeypatch.setattr(Path, "rename", _lose_the_race)

    provider = PersonalCaProvider.bootstrap(paths)

    assert provider.trust_anchor().bundle_pem() == winner.trust_anchor().bundle_pem()
    leftovers = [p for p in tmp_path.iterdir() if p != paths.dir]
    assert leftovers == []


def test_bootstrap_raises_the_clear_error_for_a_partial_ca_dir(tmp_path: Path) -> None:
    """A directory holding only one of the two required files (a prior
    save interrupted mid-write) must not be treated as empty — bootstrap
    must not build a second CA into it, nor crash with a bare error.
    """
    paths = CaPaths(tmp_path / "ca")
    paths.ensure_dir()
    paths.root_key_path.write_bytes(b"orphaned-key-no-cert")

    with pytest.raises(ValueError, match="damaged or incomplete"):
        PersonalCaProvider.bootstrap(paths)

    # No second CA was installed beside the partial material.
    assert not paths.root_cert_path.exists()
    siblings = [p for p in tmp_path.iterdir() if p != paths.dir]
    assert siblings == []


def test_bootstrap_discards_the_staging_dir_when_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure partway through writing the new CA (e.g. disk full after
    the staging directory is created but before the key finishes writing)
    must not leave a hidden directory holding a partial private key.
    """
    paths = CaPaths(tmp_path / "ca")

    def _disk_full(_self: KeyPair, _path: Path) -> None:
        msg = "no space left on device"
        raise OSError(msg)

    monkeypatch.setattr(KeyPair, "save", _disk_full)

    with pytest.raises(OSError, match="no space left"):
        PersonalCaProvider.bootstrap(paths)

    assert list(tmp_path.iterdir()) == []


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
