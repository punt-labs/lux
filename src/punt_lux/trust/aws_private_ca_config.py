"""AwsPrivateCaConfig — the per-Display configuration Provider 2 issues against.

system.tex §"Provider 2 (Optional): AWS Private CA (Managed)": everything
this class holds is the operator's own AWS-side choice — the CA ARN they
already provisioned, the algorithm their CA signs with, and which issuance
template applies — never inferred or defaulted-around by Lux, matching the
design's "Lux does not create or manage this AWS resource itself" stance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["AcmPcaSigningAlgorithm", "AwsPrivateCaConfig"]

# ACM Private CA's IssueCertificate "SigningAlgorithm" names the algorithm
# the CA signs WITH — a property of the CA's own key (RSA or ECDSA, and
# which curve/modulus), not of the leaf key the CSR carries. This package
# cannot infer it without querying the operator's own CA, so the operator
# states it explicitly. Verify the exact accepted value set against ACM
# Private CA's current IssueCertificate reference before relying on it;
# this design deliberately does not assume which one a given CA uses.
AcmPcaSigningAlgorithm = Literal[
    "SHA256WITHECDSA",
    "SHA384WITHECDSA",
    "SHA512WITHECDSA",
    "SHA256WITHRSA",
    "SHA384WITHRSA",
    "SHA512WITHRSA",
]

# AWS's general-purpose end-entity template. Confirm this still matches the
# operator's intended leaf shape (an EKU carrying both serverAuth and
# clientAuth for mTLS, and — critically — that it forwards the CSR's own
# Subject Alternative Name onto the issued leaf, the way CertificateAuthority
# .sign_csr does locally for Provider 1) against ACM Private CA's current
# template catalog before adopting it in production. A template that drops
# the CSR's SAN produces a leaf LeafCertificate.hostname cannot resolve,
# which fails loudly downstream rather than silently — but the operator
# should not have to discover that at issuance time.
_DEFAULT_TEMPLATE_ARN = "arn:aws:acm-pca:::template/EndEntityCertificate/V1"

# Mirrors Provider 1's leaf validity (certificate_authority.py) — bounds a
# leaked leaf key's damage window without the operational cost of rotating
# the CA itself.
_DEFAULT_VALIDITY_DAYS = 365


@dataclass(frozen=True, slots=True)
class AwsPrivateCaConfig:
    """The ACM Private CA identity and issuance shape Provider 2 issues against."""

    ca_authority_arn: str
    signing_algorithm: AcmPcaSigningAlgorithm
    template_arn: str = _DEFAULT_TEMPLATE_ARN
    validity_days: int = _DEFAULT_VALIDITY_DAYS

    def __post_init__(self) -> None:
        """Reject an unusable configuration before it ever reaches AWS."""
        if not self.ca_authority_arn:
            msg = "ca_authority_arn must be a non-empty ACM Private CA ARN"
            raise ValueError(msg)
        if self.validity_days <= 0:
            msg = f"validity_days must be positive, got {self.validity_days}"
            raise ValueError(msg)
