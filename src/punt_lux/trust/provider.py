"""TrustAnchorProvider — the two obligations DES-090 asks of any CA backend.

system.tex §"Trust Anchor Providers: Pluggable, Not Fixed": swapping
providers swaps what the trust anchor holds and how a leaf is issued;
nothing else in the mTLS handshake, the SAN check, or any of DES-090's four
invariants changes. Structural typing, not a base class — per the org's
"families share via Protocol" standard, any object satisfying both methods
is a valid provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
    from punt_lux.trust.leaf_certificate import LeafCertificate
    from punt_lux.trust.trust_anchor import TrustAnchor

__all__ = ["TrustAnchorProvider"]


@runtime_checkable
class TrustAnchorProvider(Protocol):
    """A trust anchor plus an issuance path — Provider 1 today, Provider 2 later."""

    def trust_anchor(self) -> TrustAnchor:
        """Return the chain a Display's ``ssl.SSLContext`` verifies leaves against."""
        ...

    def issue_leaf_certificate(self, csr: CertificateSigningRequest) -> LeafCertificate:
        """Sign *csr*, returning a leaf chaining to this provider's own anchor."""
        ...
