"""Tests for Curve: the shared P-256 enforcement boundary check."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from punt_lux.trust.curve import Curve


def test_require_p256_returns_a_p256_key_unchanged() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    assert Curve.require_p256(key) is key


def test_require_p256_rejects_a_p384_private_key() -> None:
    key = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(ValueError, match="SECP256R1"):
        Curve.require_p256(key)


def test_require_p256_rejects_a_p521_public_key() -> None:
    key = ec.generate_private_key(ec.SECP521R1()).public_key()
    with pytest.raises(ValueError, match="SECP256R1"):
        Curve.require_p256(key)
