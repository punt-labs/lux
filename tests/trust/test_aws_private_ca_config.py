"""Tests for AwsPrivateCaConfig: validation and defaults."""

from __future__ import annotations

import pytest

from punt_lux.trust.aws_private_ca_config import AwsPrivateCaConfig

_CA_ARN = "arn:aws:acm-pca:us-east-1:123456789012:certificate-authority/abc-123"


def test_defaults_produce_a_usable_config() -> None:
    config = AwsPrivateCaConfig(
        ca_authority_arn=_CA_ARN, signing_algorithm="SHA256WITHECDSA"
    )
    assert config.ca_authority_arn == _CA_ARN
    assert config.signing_algorithm == "SHA256WITHECDSA"
    assert config.template_arn.startswith("arn:aws:acm-pca:::template/")
    assert config.validity_days == 365


def test_rejects_an_empty_ca_authority_arn() -> None:
    with pytest.raises(ValueError, match="non-empty ACM Private CA ARN"):
        AwsPrivateCaConfig(ca_authority_arn="", signing_algorithm="SHA256WITHECDSA")


def test_rejects_an_arn_that_is_not_an_acm_pca_ca_arn() -> None:
    # A non-empty string that is not an ACM Private CA certificate-authority ARN
    # (e.g. an S3 ARN, or a role ARN) is rejected before it can reach AWS.
    with pytest.raises(ValueError, match="does not look like an ACM Private CA ARN"):
        AwsPrivateCaConfig(
            ca_authority_arn="arn:aws:iam::123456789012:role/some-role",
            signing_algorithm="SHA256WITHECDSA",
        )


def test_accepts_a_non_commercial_partition_arn() -> None:
    # The shape-check is partition-agnostic: aws-cn / aws-us-gov ARNs carry the
    # same :acm-pca: and :certificate-authority/ segments and must be accepted.
    govcloud_arn = (
        "arn:aws-us-gov:acm-pca:us-gov-west-1:123456789012:"
        "certificate-authority/abc-123"
    )
    config = AwsPrivateCaConfig(
        ca_authority_arn=govcloud_arn, signing_algorithm="SHA256WITHECDSA"
    )
    assert config.ca_authority_arn == govcloud_arn


def test_rejects_a_non_positive_validity() -> None:
    with pytest.raises(ValueError, match="validity_days must be positive"):
        AwsPrivateCaConfig(
            ca_authority_arn=_CA_ARN,
            signing_algorithm="SHA256WITHECDSA",
            validity_days=0,
        )


def test_is_frozen() -> None:
    config = AwsPrivateCaConfig(
        ca_authority_arn=_CA_ARN, signing_algorithm="SHA256WITHECDSA"
    )
    with pytest.raises(AttributeError):
        config.ca_authority_arn = "arn:aws:acm-pca:us-east-1:123456789012:other"  # type: ignore[misc]
