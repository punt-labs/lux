"""EnrolledIdentity — the private key and signed leaf a Hub uses for mTLS.

The end state of enrollment (system.tex §"Authentication and Enrollment",
step 4): what W8/W10's ``ssl.SSLContext`` load as the client-certificate
side of the cross-host handshake.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self, final

from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.leaf_certificate import LeafCertificate

__all__ = ["EnrolledIdentity"]


@final
class EnrolledIdentity:
    """A machine's private key paired with its CA-signed leaf certificate."""

    _key_pair: KeyPair
    _leaf: LeafCertificate
    __slots__ = ("_key_pair", "_leaf")

    def __new__(cls, key_pair: KeyPair, leaf: LeafCertificate) -> Self:
        self = super().__new__(cls)
        self._key_pair = key_pair
        self._leaf = leaf
        return self

    @property
    def hostname(self) -> str:
        """Return the hostname this identity's leaf certifies."""
        return self._leaf.hostname

    @property
    def leaf(self) -> LeafCertificate:
        """Return the signed leaf certificate half of this identity."""
        return self._leaf

    def key_pem(self) -> bytes:
        """Return the private key as PEM, for handoff to ``ssl.SSLContext``."""
        return self._key_pair.to_pem()

    def certificate_pem(self) -> bytes:
        """Return the leaf certificate as PEM."""
        return self._leaf.to_pem()

    def save(self, key_path: Path, cert_path: Path) -> None:
        """Persist the private key (``0600``) and certificate to disk."""
        self._key_pair.save(key_path)
        self._leaf.save(cert_path)

    @classmethod
    def load(cls, key_path: Path, cert_path: Path) -> Self:
        """Load a previously-saved identity from its key and certificate files."""
        return cls(KeyPair.load(key_path), LeafCertificate.load(cert_path))
