"""KeyPair — an ECDSA private key, encapsulated so it never leaves the class
except by explicit, deliberate serialization.

The signing operations a certificate authority and a CSR requester both need
(sign a builder, expose the public key) live here; every caller that wants a
signature hands this class a builder rather than reaching for the raw key.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hashes import SHA256

if TYPE_CHECKING:
    from cryptography import x509

__all__ = ["KeyPair"]

# NIST P-256 — the modern default curve for TLS leaf/CA keys (RFC 8446 §4.2.7's
# default group, matched by every current browser and OpenSSL build).
_CURVE = ec.SECP256R1()


@final
class KeyPair:
    """An ECDSA keypair. Signs builders; never exposes the raw private key."""

    _private_key: ec.EllipticCurvePrivateKey
    __slots__ = ("_private_key",)

    def __new__(cls, private_key: ec.EllipticCurvePrivateKey) -> Self:
        self = super().__new__(cls)
        self._private_key = private_key
        return self

    @classmethod
    def generate(cls) -> Self:
        """Generate a fresh P-256 keypair."""
        return cls(ec.generate_private_key(_CURVE))

    @classmethod
    def from_pem(cls, pem: bytes) -> Self:
        """Load an unencrypted PEM-encoded private key.

        Raises :class:`ValueError` if the key is not an EC key — the only
        kind this class, and every certificate it signs, is built to hold.
        """
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            msg = f"expected an EC private key, got {type(key).__name__}"
            raise ValueError(msg)
        return cls(key)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a keypair from a PEM file on disk."""
        return cls.from_pem(path.read_bytes())

    @property
    def public_key(self) -> ec.EllipticCurvePublicKey:
        """Return the public half — safe to hand to any caller."""
        return self._private_key.public_key()

    def public_key_pem(self) -> bytes:
        """Return the public key as PEM-encoded SubjectPublicKeyInfo.

        Used to compare two keypairs' public identity without depending on
        ``cryptography``'s public-key equality semantics directly.
        """
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def to_pem(self) -> bytes:
        """Serialize the private key as unencrypted PKCS8 PEM.

        Unencrypted at this layer because the filesystem permission
        (``0600``, applied by :meth:`save`) is this design's stated
        protection for key material at rest — the same discipline the
        socket directory already uses (system.tex §"Authentication and
        Enrollment"). A passphrase layer belongs to the CLI that calls this,
        not this value class.
        """
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def save(self, path: Path) -> None:
        """Write the private key to *path* as ``0600``."""
        path.write_bytes(self.to_pem())
        path.chmod(0o600)

    def sign_csr_builder(
        self, builder: x509.CertificateSigningRequestBuilder
    ) -> x509.CertificateSigningRequest:
        """Sign *builder* with this keypair, producing a CSR."""
        return builder.sign(self._private_key, SHA256())

    def sign_certificate_builder(
        self, builder: x509.CertificateBuilder
    ) -> x509.Certificate:
        """Sign *builder* with this keypair, producing a certificate."""
        return builder.sign(self._private_key, SHA256())
