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
