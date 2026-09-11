"""Tests for KeyPair: generation, PEM roundtrip, disk persistence, signing."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from punt_lux.trust.key_pair import KeyPair


def test_generate_produces_an_ec_p256_key() -> None:
    pair = KeyPair.generate()
    assert isinstance(pair.public_key.curve, ec.SECP256R1)


def test_from_pem_rejects_a_non_p256_curve() -> None:
    from cryptography.hazmat.primitives import serialization

    non_p256 = ec.generate_private_key(ec.SECP384R1())
    pem = non_p256.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="SECP256R1"):
        KeyPair.from_pem(pem)


def test_pem_roundtrip_preserves_the_key() -> None:
    original = KeyPair.generate()
    restored = KeyPair.from_pem(original.to_pem())
    assert restored.public_key_pem() == original.public_key_pem()


@pytest.mark.slow
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


def test_save_ignores_a_permissive_umask(tmp_path: Path) -> None:
    path = tmp_path / "key.pem"
    old_umask = os.umask(0o000)
    try:
        KeyPair.generate().save(path)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_is_never_briefly_readable_before_the_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file must already be ``0600`` by the time any bytes hit disk.

    Spies on ``os.write`` to sample the file's mode at the moment of the
    first write — the historical bug wrote the PEM with ``write_bytes()``
    (creating the file under the process umask) and only chmodded to
    ``0600`` afterward, leaving a window where a concurrent reader could
    see the unencrypted private key.
    """
    path = tmp_path / "key.pem"
    modes_at_write: list[int] = []
    real_write = os.write

    def spy_write(fd: int, data: bytes) -> int:
        modes_at_write.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy_write)
    KeyPair.generate().save(path)
    assert modes_at_write == [0o600]


def test_save_normalizes_permissions_on_a_preexisting_insecure_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "key.pem"
    path.write_bytes(b"stale")
    path.chmod(0o644)
    KeyPair.generate().save(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


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
