"""Tests for _AcmPcaClient: the structural boto3-shaped contract.

Mirrors ``test_provider.py``'s style for ``TrustAnchorProvider``: the
protocol has no implementation of its own, so these tests assert the
family-membership contract — an unrelated fake with the right methods
satisfies it, one missing a method does not, and a real ``boto3`` ACM
Private CA client satisfies it too (structural typing needs no adapter).
"""

from __future__ import annotations

from typing import Literal

import boto3

from punt_lux.trust._acm_pca_client import _AcmPcaClient


class _FakeWaiter:
    def wait(self, **_kwargs: str) -> None:
        return None


class _FakeClient:
    """An unrelated stand-in with no relation to boto3 whatsoever."""

    def issue_certificate(self, **_kwargs: object) -> dict[str, str]:
        return {"CertificateArn": "arn:aws:acm-pca:::certificate/fake"}

    def get_certificate(self, **_kwargs: str) -> dict[str, str]:
        return {"Certificate": "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----"}

    def get_certificate_authority_certificate(self, **_kwargs: str) -> dict[str, str]:
        return {"Certificate": "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----"}

    def get_waiter(self, waiter_name: Literal["certificate_issued"]) -> _FakeWaiter:
        assert waiter_name == "certificate_issued"
        return _FakeWaiter()


class _MissingWaiterMethod:
    """Has three of the four required methods."""

    def issue_certificate(self, **_kwargs: object) -> dict[str, str]:
        return {}

    def get_certificate(self, **_kwargs: str) -> dict[str, str]:
        return {}

    def get_certificate_authority_certificate(self, **_kwargs: str) -> dict[str, str]:
        return {}


def test_an_unrelated_class_with_all_four_methods_satisfies_the_protocol() -> None:
    assert isinstance(_FakeClient(), _AcmPcaClient)


def test_a_class_missing_get_waiter_does_not_satisfy_the_protocol() -> None:
    assert isinstance(_MissingWaiterMethod(), _AcmPcaClient) is False


def test_a_real_boto3_acm_pca_client_satisfies_the_protocol() -> None:
    """The whole point of a structural Protocol: boto3 never imports this
    package, and this package never subclasses boto3, yet the real client
    boto3 hands back is a valid ``_AcmPcaClient`` by having the methods.

    Constructing a boto3 client is a local operation: it loads the service
    model from disk and builds an endpoint resolver, making no network call
    and resolving no credentials (both are deferred to the first API call).
    Passing ``region_name`` explicitly also skips ambient region resolution,
    so this test cannot stall or require live AWS. The region assertion pins
    that the explicit region is the one the client actually uses.
    """
    client = boto3.client("acm-pca", region_name="us-east-1")
    # Region check first, while ``client`` is still boto3's untyped Any — the
    # isinstance narrowing below rebinds it to the _AcmPcaClient Protocol,
    # which does not (and should not) expose boto3's ``meta``.
    assert client.meta.region_name == "us-east-1"
    assert isinstance(client, _AcmPcaClient)
