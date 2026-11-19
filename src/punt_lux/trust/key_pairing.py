"""Enforce matching public keys across private keys and signed material.

Checked once, at construction, so a mismatched pair is rejected before it is ever used
for a handshake or a signing operation (DES-090).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from cryptography.hazmat.primitives import serialization

if TYPE_CHECKING:
    from cryptography import x509

__all__ = ["Pairing"]


@runtime_checkable
class KeyedByPublicKeyPem(Protocol):
    """Anything that can report its own public key as PEM."""

    def public_key_pem(self) -> bytes: ...


class Pairing:
    """Namespace for the key/certificate public-key pairing invariant."""

    @staticmethod
    def require_matching(
        a: KeyedByPublicKeyPem, b: KeyedByPublicKeyPem, what: str
    ) -> None:
        """Require both objects to report the same public key."""
        Pairing.require_matching_pem(a.public_key_pem(), b.public_key_pem(), what)

    @staticmethod
    def require_matching_certificate(
        key_pair: KeyedByPublicKeyPem, certificate: x509.Certificate, what: str
    ) -> None:
        """Require the key pair to match the certificate's public key."""
        cert_pem = certificate.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        Pairing.require_matching_pem(key_pair.public_key_pem(), cert_pem, what)

    @staticmethod
    def require_matching_pem(a: bytes, b: bytes, what: str) -> None:
        """Require the two PEM values to match byte for byte."""
        if a != b:
            msg = f"key pair does not match {what}'s public key"
            raise ValueError(msg)
