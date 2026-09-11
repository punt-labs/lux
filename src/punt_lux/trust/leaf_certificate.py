"""LeafCertificate — a signed X.509 certificate naming exactly one hostname.

What a CA hands back after signing a CSR — system.tex §"Resolving the
Trust Fork" derives a connection's verified hostname from this material.
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
    def from_der(cls, der: bytes) -> Self:
        """Load a DER-encoded certificate -- the form
        ``ssl.SSLSocket.getpeercert(binary_form=True)`` returns for an
        already mTLS-verified peer (system.tex §"Resolving the Trust Fork").
        """
        return cls(x509.load_der_x509_certificate(der))

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a certificate from a PEM file on disk."""
        return cls.from_pem(path.read_bytes())

    def to_pem(self) -> bytes:
        """Serialize this certificate as PEM."""
        return self._certificate.public_bytes(serialization.Encoding.PEM)

    def to_der(self) -> bytes:
        """Serialize this certificate as DER -- :meth:`from_der`'s inverse."""
        return self._certificate.public_bytes(serialization.Encoding.DER)

    def save(self, path: Path) -> None:
        """Write this certificate to *path* as PEM. A certificate is public."""
        path.write_bytes(self.to_pem())

    def public_key_pem(self) -> bytes:
        """Return this leaf's public key as PEM SubjectPublicKeyInfo, to
        compare pairing with a key without cryptography's own equality.
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
    def not_valid_before(self) -> datetime:
        """Return the certificate's start of validity, timezone-aware (UTC)."""
        return self._certificate.not_valid_before_utc

    @property
    def not_valid_after(self) -> datetime:
        """Return the certificate's expiry, timezone-aware (UTC)."""
        return self._certificate.not_valid_after_utc

    def is_expired(self) -> bool:
        """Return whether this certificate has expired as of now."""
        return datetime.now(UTC) >= self._certificate.not_valid_after_utc

    def is_expired_as_of(self, at: datetime) -> bool:
        """Return whether this certificate is expired as of *at* (test hook)."""
        return at >= self._certificate.not_valid_after_utc

    @property
    def hostname(self) -> str:
        """Return the single SAN DNSName this leaf certifies, or raise if
        the SAN is absent or does not name exactly one hostname.
        """
        names = self._dns_names()
        if len(names) != 1:
            msg = f"leaf must name exactly one SAN DNSName, found {len(names)}"
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
