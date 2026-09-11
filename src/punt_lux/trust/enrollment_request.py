"""EnrollmentRequest — a Hub machine's local half of enrollment.

A fresh keypair and CSR, generated entirely on the Hub's own machine — the
private key never leaves it. The CSR crosses to wherever the CA lives (an
offline copy for Provider 1, an API call for Provider 2) and comes back as
a signed leaf, which :meth:`EnrollmentRequest.complete` pairs with the key
that never travelled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.enrolled_identity import EnrolledIdentity
from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.leaf_certificate import LeafCertificate

__all__ = ["EnrollmentRequest"]


@final
class EnrollmentRequest:
    """A freshly generated keypair and its outgoing CSR, for one hostname."""

    _key_pair: KeyPair
    _csr: CertificateSigningRequest
    __slots__ = ("_csr", "_key_pair")

    def __new__(cls, key_pair: KeyPair, csr: CertificateSigningRequest) -> Self:
        self = super().__new__(cls)
        self._key_pair = key_pair
        self._csr = csr
        return self

    @classmethod
    def generate(cls, hostname: str) -> Self:
        """Generate a fresh keypair and a CSR naming *hostname*."""
        key_pair = KeyPair.generate()
        return cls(key_pair, CertificateSigningRequest.generate(hostname, key_pair))

    @property
    def csr(self) -> CertificateSigningRequest:
        """Return the CSR half of this request — the part that crosses machines."""
        return self._csr

    def save(self, key_path: Path, csr_path: Path) -> None:
        """Persist the private key (``0600``) and CSR to disk."""
        self._key_pair.save(key_path)
        self._csr.save(csr_path)

    def complete(self, leaf: LeafCertificate) -> EnrolledIdentity:
        """Pair this request's private key with the CA's returned *leaf*.

        Raises :class:`ValueError` if *leaf*'s public key does not match
        this request's — the check that the signature-carrying half of the
        chain actually corresponds to the key that never left this machine.
        """
        if leaf.public_key_pem() != self._key_pair.public_key_pem():
            msg = "leaf certificate does not match this enrollment request's key"
            raise ValueError(msg)
        return EnrolledIdentity(self._key_pair, leaf)
