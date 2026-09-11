"""CertificateSigningRequest — a PKCS10 CSR naming exactly one DNS hostname.

Generated on a Hub machine as its half of enrollment (system.tex
§"Authentication and Enrollment", step 3): the private key stays put, and
only this request crosses to wherever the CA lives.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from punt_lux.trust._facade import _TrustFacade

if TYPE_CHECKING:
    from punt_lux.trust.key_pair import KeyPair

__all__ = ["CertificateSigningRequest"]


@final
class CertificateSigningRequest:
    """A CSR whose Subject Alternative Name is exactly one DNS hostname."""

    _csr: x509.CertificateSigningRequest
    __slots__ = ("_csr",)

    def __new__(cls, csr: x509.CertificateSigningRequest) -> Self:
        self = super().__new__(cls)
        self._csr = csr
        _ = self.public_key  # raises unless the CSR's key is P-256 (DES-090)
        return self

    @classmethod
    def generate(cls, hostname: str, key_pair: KeyPair) -> Self:
        """Build and sign a CSR naming *hostname*, using *key_pair*'s key."""
        builder = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        )
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        return cls(key_pair.sign_csr_builder(builder))

    @classmethod
    def from_pem(cls, pem: bytes) -> Self:
        """Load a PEM-encoded CSR."""
        return cls(x509.load_pem_x509_csr(pem))

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a CSR from a PEM file on disk."""
        return cls.from_pem(path.read_bytes())

    def to_pem(self) -> bytes:
        """Serialize this CSR as PEM."""
        return self._csr.public_bytes(serialization.Encoding.PEM)

    def save(self, path: Path) -> None:
        """Write this CSR to *path* as PEM. A CSR carries no secret material."""
        path.write_bytes(self.to_pem())

    @property
    def subject(self) -> x509.Name:
        """Return the CSR's subject name, to carry forward onto its leaf."""
        return self._csr.subject

    @property
    def public_key(self) -> ec.EllipticCurvePublicKey:
        """Return the public key this CSR requests a certificate for."""
        key = self._csr.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey):
            msg = f"expected an EC public key, got {type(key).__name__}"
            raise ValueError(msg)
        return _TrustFacade.require_p256(key)

    @property
    def is_signature_valid(self) -> bool:
        """Return whether the CSR's self-signature verifies against its key
        — proof, before signing, that the requester actually holds it.
        """
        return self._csr.is_signature_valid

    @property
    def hostname(self) -> str:
        """Return the single SAN DNSName this CSR requests.

        Raises :class:`ValueError` unless the SAN names exactly one DNS
        hostname — DES-090 binds every leaf to exactly one machine.
        """
        names = self._dns_names()
        if len(names) != 1:
            msg = f"CSR must have exactly one SAN DNSName, found {len(names)}"
            raise ValueError(msg)
        return names[0]

    def _dns_names(self) -> list[str]:
        try:
            ext = self._csr.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
        except x509.ExtensionNotFound:
            return []
        return ext.value.get_values_for_type(x509.DNSName)
