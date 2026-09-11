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
    # (e.g. an IAM role ARN) is rejected before it can reach AWS.
    with pytest.raises(ValueError, match="well-formed ACM Private CA"):
        AwsPrivateCaConfig(
            ca_authority_arn="arn:aws:iam::123456789012:role/some-role",
            signing_algorithm="SHA256WITHECDSA",
        )


def test_rejects_an_arn_missing_a_region() -> None:
    # The client's region is derived from the ARN's region segment, so a CA ARN
    # with an empty region is rejected at construction rather than producing a
    # client with no region that fails opaquely on the first AWS call.
    with pytest.raises(ValueError, match="well-formed ACM Private CA"):
        AwsPrivateCaConfig(
            ca_authority_arn="arn:aws:acm-pca::123456789012:certificate-authority/x",
            signing_algorithm="SHA256WITHECDSA",
        )


def test_region_and_partition_are_parsed_from_the_ca_arn() -> None:
    config = AwsPrivateCaConfig(
        ca_authority_arn=_CA_ARN, signing_algorithm="SHA256WITHECDSA"
    )
    assert config.region == "us-east-1"
    assert config.partition == "aws"


def test_accepts_a_non_commercial_partition_and_derives_its_template() -> None:
    # aws-us-gov CAs must work end to end, not merely pass the ARN shape-check:
    # AWS's predefined template ARNs are partition-scoped, so the default
    # template must land in the CA's own partition, not the commercial one.
    govcloud_arn = (
        "arn:aws-us-gov:acm-pca:us-gov-west-1:123456789012:"
        "certificate-authority/abc-123"
    )
    config = AwsPrivateCaConfig(
        ca_authority_arn=govcloud_arn, signing_algorithm="SHA256WITHECDSA"
    )
    assert config.ca_authority_arn == govcloud_arn
    assert config.partition == "aws-us-gov"
    assert config.region == "us-gov-west-1"
    assert config.template_arn == (
        "arn:aws-us-gov:acm-pca:::template/EndEntityCertificate/V1"
    )


def test_an_explicit_template_arn_overrides_the_partition_default() -> None:
    override = "arn:aws:acm-pca:::template/CodeSigningCertificate/V1"
    config = AwsPrivateCaConfig(
        ca_authority_arn=_CA_ARN,
        signing_algorithm="SHA256WITHECDSA",
        template_arn=override,
    )
    assert config.template_arn == override


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
