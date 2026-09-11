"""TrustAnchor — the certificate chain a Display verifies incoming leaves against.

Obligation 1 of the pluggable trust-anchor-provider interface (system.tex
§"Trust Anchor Providers: Pluggable, Not Fixed"): what an ``ssl.SSLContext``
loads as its verification set. Swapping providers swaps what this holds;
nothing else in the mTLS handshake or the SAN check changes.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterable
from typing import Self, final

__all__ = ["TrustAnchor"]


@final
class TrustAnchor:
    """A root (and any intermediate) certificate chain, as PEM bundles."""

    _certificates_pem: tuple[bytes, ...]
    __slots__ = ("_certificates_pem",)

    def __new__(cls, certificates_pem: Iterable[bytes]) -> Self:
        self = super().__new__(cls)
        self._certificates_pem = tuple(certificates_pem)
        if not self._certificates_pem:
            msg = "a trust anchor needs at least one certificate"
            raise ValueError(msg)
        return self

    def bundle_pem(self) -> bytes:
        """Return every anchor certificate concatenated as one PEM bundle.

        ``ssl.SSLContext``'s ``cadata`` and OpenSSL's CA-file loading both
        accept a concatenated chain of PEM blocks.
        """
        return b"\n".join(self._certificates_pem)

    def build_ssl_context(
        self, purpose: ssl.Purpose = ssl.Purpose.CLIENT_AUTH
    ) -> ssl.SSLContext:
        """Return a fail-closed ``ssl.SSLContext`` verifying against this anchor.

        *purpose* defaults to ``CLIENT_AUTH`` — the Display's own use,
        verifying an incoming Hub's client certificate (system.tex
        §"Transport Specification"). Pass ``ssl.Purpose.SERVER_AUTH`` to
        verify a Display's server leaf from the Hub side instead. TLS 1.3
        and mandatory peer verification are this design's stated minimums,
        not the caller's to opt out of.
        """
        context = ssl.create_default_context(
            purpose, cadata=self.bundle_pem().decode("ascii")
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        return context
