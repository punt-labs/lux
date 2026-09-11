"""Tests for KeyPair: generation, PEM roundtrip, disk persistence, signing."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from punt_lux.trust.key_pair import KeyPair


def test_generate_produces_an_ec_p256_key() -> None:
    pair = KeyPair.generate()
    assert isinstance(pair.public_key.curve, ec.SECP256R1)


def test_pem_roundtrip_preserves_the_key() -> None:
    original = KeyPair.generate()
    restored = KeyPair.from_pem(original.to_pem())
    assert restored.public_key_pem() == original.public_key_pem()


def test_from_pem_rejects_a_non_ec_key() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="EC private key"):
        KeyPair.from_pem(pem)


def test_save_writes_the_key_as_0600(tmp_path: Path) -> None:
    path = tmp_path / "key.pem"
    KeyPair.generate().save(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "key.pem"
    original = KeyPair.generate()
    original.save(path)
    restored = KeyPair.load(path)
    assert restored.public_key_pem() == original.public_key_pem()


def test_two_generated_keypairs_are_distinct() -> None:
    a = KeyPair.generate()
    b = KeyPair.generate()
    assert a.public_key_pem() != b.public_key_pem()
