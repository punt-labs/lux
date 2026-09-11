"""Tests for _TrustFacade: the mediator pass-through onto every primitive."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from punt_lux.trust._facade import _TrustFacade
from punt_lux.trust.certificate_authority import CertificateAuthority

_HOSTNAME = "hub1.example.com"


def test_require_p256_passes_through_to_curve() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    assert _TrustFacade.require_p256(key) is key


def test_require_p256_rejects_a_non_p256_key() -> None:
    key = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(ValueError, match="SECP256R1"):
        _TrustFacade.require_p256(key)


def test_require_matching_passes_through_to_pairing() -> None:
    key_pair, leaf = CertificateAuthority.create().issue_leaf(_HOSTNAME)
    _TrustFacade.require_matching(key_pair, leaf, "the leaf")  # must not raise


def test_require_matching_rejects_a_mismatch() -> None:
    ca = CertificateAuthority.create()
    _key_a, leaf_a = ca.issue_leaf("a.example.com")
    key_b, _leaf_b = ca.issue_leaf("b.example.com")
    with pytest.raises(ValueError, match="does not match"):
        _TrustFacade.require_matching(key_b, leaf_a, "the leaf")


def test_require_matching_certificate_passes_through_to_pairing() -> None:
    key_pair, leaf = CertificateAuthority.create().issue_leaf(_HOSTNAME)
    raw_cert = x509.load_pem_x509_certificate(leaf.to_pem())
    _TrustFacade.require_matching_certificate(key_pair, raw_cert, "the leaf")


def test_load_or_raise_clearly_passes_through_to_material_load(
    tmp_path: Path,
) -> None:
    result = _TrustFacade.load_or_raise_clearly(tmp_path, lambda: "loaded")
    assert result == "loaded"


def test_load_or_raise_clearly_wraps_a_value_error(tmp_path: Path) -> None:
    def _boom() -> None:
        msg = "underlying failure"
        raise ValueError(msg)

    with pytest.raises(ValueError, match=str(tmp_path)):
        _TrustFacade.load_or_raise_clearly(tmp_path, _boom)


def test_atomic_install_returns_a_staging_sibling(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    install = _TrustFacade.atomic_install(dest)
    assert install.staging_dir.parent == dest.parent
    assert install.staging_dir != dest
