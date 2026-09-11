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

# The AWS-predefined general-purpose end-entity template, everything after the
# partition segment. Confirm this still matches the operator's intended leaf
# shape (an EKU carrying both serverAuth and clientAuth for mTLS, and —
# critically — that it forwards the CSR's own Subject Alternative Name onto the
# issued leaf, the way CertificateAuthority.sign_csr does locally for Provider
# 1) against ACM Private CA's current template catalog before adopting it in
# production. A template that drops the CSR's SAN produces a leaf
# LeafCertificate.hostname cannot resolve, which fails loudly downstream rather
# than silently — but the operator should not have to discover that at issuance
# time. The partition is not hardcoded here: AWS's predefined template ARNs are
# partition-scoped, so the default is built from the CA ARN's own partition
# (see _default_template_arn) — a hardcoded arn:aws: default would make every
# GovCloud (arn:aws-us-gov:) or China (arn:aws-cn:) issuance fail.
_TEMPLATE_RESOURCE = "acm-pca:::template/EndEntityCertificate/V1"

# ARN layout: arn:PARTITION:SERVICE:REGION:ACCOUNT:RESOURCE (six segments).
_ARN_SEGMENTS = 6
_ARN_PARTITION = 1
_ARN_SERVICE = 2
_ARN_REGION = 3
_ARN_RESOURCE = 5

# Mirrors Provider 1's leaf validity (certificate_authority.py) — bounds a
# leaked leaf key's damage window without the operational cost of rotating
# the CA itself.
_DEFAULT_VALIDITY_DAYS = 365


@dataclass(frozen=True, slots=True)
class AwsPrivateCaConfig:
    """The ACM Private CA identity and issuance shape Provider 2 issues against."""

    ca_authority_arn: str
    signing_algorithm: AcmPcaSigningAlgorithm
    # Empty means "derive the partition-correct AWS default in __post_init__" —
    # a discriminated "not overridden" state, not an absent value; after
    # __post_init__ this is always a full ARN. A non-empty value is the
    # operator's explicit template override.
    template_arn: str = ""
    validity_days: int = _DEFAULT_VALIDITY_DAYS

    def __post_init__(self) -> None:
        """Reject an unusable configuration before it ever reaches AWS."""
        self._reject_malformed_arn()
        if not self.template_arn:
            object.__setattr__(
                self, "template_arn", self._default_template_arn(self.partition)
            )
        if self.validity_days <= 0:
            msg = f"validity_days must be positive, got {self.validity_days}"
            raise ValueError(msg)

    @property
    def partition(self) -> str:
        """The AWS partition segment of the CA ARN (``aws``, ``aws-us-gov``,
        ``aws-cn``) — the CA ARN is validated in ``__post_init__``, so the
        segment is always present.
        """
        return self.ca_authority_arn.split(":")[_ARN_PARTITION]

    @property
    def region(self) -> str:
        """The AWS region segment of the CA ARN. The ACM Private CA client must
        talk to the region the CA lives in, so Provider 2 derives the client's
        region from this rather than boto3's ambient default — a client pointed
        at the wrong region fails confusingly against a CA that "does not exist"
        there.
        """
        return self.ca_authority_arn.split(":")[_ARN_REGION]

    def _reject_malformed_arn(self) -> None:
        """Raise unless ``ca_authority_arn`` is a well-formed ACM Private CA
        certificate-authority ARN carrying a partition and a region.
        """
        if not self.ca_authority_arn:
            msg = "ca_authority_arn must be a non-empty ACM Private CA ARN"
            raise ValueError(msg)
        segments = self.ca_authority_arn.split(":")
        # Partition-agnostic (arn:aws:, arn:aws-cn:, arn:aws-us-gov:) — checks
        # the structural segments every partition shares, and that partition
        # and region (which Provider 2 derives the client's region from) are
        # both present.
        well_formed = (
            len(segments) >= _ARN_SEGMENTS
            and segments[0] == "arn"
            and bool(segments[_ARN_PARTITION])
            and segments[_ARN_SERVICE] == "acm-pca"
            and bool(segments[_ARN_REGION])
            and segments[_ARN_RESOURCE].startswith("certificate-authority/")
        )
        if not well_formed:
            msg = (
                "ca_authority_arn is not a well-formed ACM Private CA "
                "certificate-authority ARN (expected "
                "arn:PARTITION:acm-pca:REGION:ACCOUNT:certificate-authority/ID): "
                f"{self.ca_authority_arn!r}"
            )
            raise ValueError(msg)

    @staticmethod
    def _default_template_arn(partition: str) -> str:
        """Build the AWS-predefined end-entity template ARN for *partition* —
        partition-scoped so GovCloud and China CAs get a template ARN in their
        own partition rather than a commercial-partition one AWS would reject.
        """
        return f"arn:{partition}:{_TEMPLATE_RESOURCE}"
