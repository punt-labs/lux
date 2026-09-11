"""LeafCertificate — a signed X.509 certificate naming exactly one hostname.

The material a CA hands back after signing a
:class:`.certificate_signing_request.CertificateSigningRequest` — what
system.tex §"Resolving the Trust Fork" calls the material the transport
derives a connection's verified hostname from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Self, final

from cryptography import x509
from cryptography.hazmat.primitives import serialization

__all__ = ["LeafCertificate"]


@final
class LeafCertificate:
    """A signed certificate whose Subject Alternative Name is one hostname."""

    _certificate: x509.Certificate
    __slots__ = ("_certificate",)

    def __new__(cls, certificate: x509.Certificate) -> Self:
        self = super().__new__(cls)
        self._certificate = certificate
        return self

    @classmethod
    def from_pem(cls, pem: bytes) -> Self:
        """Load a PEM-encoded certificate."""
        return cls(x509.load_pem_x509_certificate(pem))

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a certificate from a PEM file on disk."""
        return cls.from_pem(path.read_bytes())

    def to_pem(self) -> bytes:
        """Serialize this certificate as PEM."""
        return self._certificate.public_bytes(serialization.Encoding.PEM)

    def save(self, path: Path) -> None:
        """Write this certificate to *path* as PEM. A certificate is public."""
        path.write_bytes(self.to_pem())

    def public_key_pem(self) -> bytes:
        """Return this leaf's public key as PEM SubjectPublicKeyInfo.

        Used to confirm a leaf pairs with the private key an enrollment
        request generated, without comparing ``cryptography`` key objects
        directly.
        """
        return self._certificate.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @property
    def issuer(self) -> x509.Name:
        """Return the issuing CA's subject name."""
        return self._certificate.issuer

    @property
    def not_valid_after(self) -> datetime:
        """Return the certificate's expiry, timezone-aware (UTC)."""
        return self._certificate.not_valid_after_utc

    def is_expired(self, *, at: datetime | None = None) -> bool:
        """Return whether this certificate has expired as of *at* (default: now)."""
        return (at or datetime.now(UTC)) >= self.not_valid_after

    @property
    def hostname(self) -> str:
        """Return the single SAN DNSName this leaf certifies.

        Raises :class:`ValueError` if the SAN extension is absent or does
        not name exactly one DNS hostname.
        """
        names = self._dns_names()
        if len(names) != 1:
            msg = (
                "leaf certificate must have exactly one SAN DNSName, "
                f"found {len(names)}"
            )
            raise ValueError(msg)
        return names[0]

    def _dns_names(self) -> list[str]:
        try:
            ext = self._certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
        except x509.ExtensionNotFound:
            return []
        return ext.value.get_values_for_type(x509.DNSName)
