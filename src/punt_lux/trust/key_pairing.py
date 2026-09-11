"""Public-key pairing — the invariant every (key, signed material) pair in
this package holds: an EnrolledIdentity's key and leaf, a
CertificateAuthority's key and root. Checked once, at construction, so a
mismatched pair is rejected before it is ever used for a handshake or a
signing operation (DES-090).
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
        """Raise :class:`ValueError` naming *what* unless *a* and *b*
        report the same public key.
        """
        Pairing.require_matching_pem(a.public_key_pem(), b.public_key_pem(), what)

    @staticmethod
    def require_matching_certificate(
        key_pair: KeyedByPublicKeyPem, certificate: x509.Certificate, what: str
    ) -> None:
        """Raise :class:`ValueError` naming *what* unless *key_pair* and
        *certificate* share a public key — for a raw ``x509.Certificate``
        with no :meth:`public_key_pem` of its own.
        """
        cert_pem = certificate.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        Pairing.require_matching_pem(key_pair.public_key_pem(), cert_pem, what)

    @staticmethod
    def require_matching_pem(a: bytes, b: bytes, what: str) -> None:
        """Raise :class:`ValueError` naming *what* unless PEM blobs *a*
        and *b* are byte-identical.
        """
        if a != b:
            msg = f"key pair does not match {what}'s public key"
            raise ValueError(msg)
