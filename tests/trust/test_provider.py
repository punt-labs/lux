"""Tests for the TrustAnchorProvider protocol itself.

The protocol has no implementation of its own to test directly — these
tests assert the family-membership contract: an object satisfies
``TrustAnchorProvider`` structurally by having the two methods, with no
base class required (the org's "families share via Protocol" standard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.trust.provider import TrustAnchorProvider

if TYPE_CHECKING:
    from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
    from punt_lux.trust.leaf_certificate import LeafCertificate
    from punt_lux.trust.trust_anchor import TrustAnchor


class _FakeProvider:
    """A minimal stand-in with no relation to PersonalCaProvider whatsoever.

    Satisfying the protocol by having the two methods — never by
    inheriting anything — is exactly the property under test.
    """

    def trust_anchor(self) -> TrustAnchor:
        raise NotImplementedError

    def issue_leaf_certificate(self, csr: CertificateSigningRequest) -> LeafCertificate:
        raise NotImplementedError


class _NotAProvider:
    """Has neither method — must not satisfy the protocol."""


def test_an_unrelated_class_with_both_methods_satisfies_the_protocol() -> None:
    assert isinstance(_FakeProvider(), TrustAnchorProvider)


def test_a_class_missing_both_methods_does_not_satisfy_the_protocol() -> None:
    assert isinstance(_NotAProvider(), TrustAnchorProvider) is False


def test_personal_ca_provider_satisfies_the_protocol() -> None:
    from punt_lux.trust.certificate_authority import CertificateAuthority
    from punt_lux.trust.personal_ca_provider import PersonalCaProvider

    provider = PersonalCaProvider(CertificateAuthority.create())
    assert isinstance(provider, TrustAnchorProvider)
