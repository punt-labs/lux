"""PersonalCaProvider — Provider 1, the default trust-anchor provider.

system.tex §"Trust Anchor Providers": free, single-machine key custody,
offline CSR-exchange enrollment. Satisfies
:class:`~punt_lux.trust.provider.TrustAnchorProvider` structurally — no
base class, per the org's "families share via Protocol" standard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.trust.atomic_dir_install import AtomicDirInstall
from punt_lux.trust.ca_paths import CaPaths
from punt_lux.trust.certificate_authority import CertificateAuthority
from punt_lux.trust.enrolled_identity import EnrolledIdentity

if TYPE_CHECKING:
    from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
    from punt_lux.trust.leaf_certificate import LeafCertificate
    from punt_lux.trust.trust_anchor import TrustAnchor

__all__ = ["PersonalCaProvider"]


@final
class PersonalCaProvider:
    """A self-managed personal CA, wrapped as a trust-anchor provider."""

    _ca: CertificateAuthority
    __slots__ = ("_ca",)

    def __new__(cls, ca: CertificateAuthority) -> Self:
        self = super().__new__(cls)
        self._ca = ca
        return self

    @classmethod
    def bootstrap(cls, paths: CaPaths) -> Self:
        """Load the personal CA at *paths*, or create and save a new one.

        Safe under concurrent first starts — an :class:`AtomicDirInstall`
        rename loser discards its own CA and loads the winner's instead.
        """
        if paths.exists():
            return cls(CertificateAuthority.load(paths))
        ca = CertificateAuthority.create()
        install = AtomicDirInstall(paths.dir)
        ca.save(CaPaths(install.staging_dir))
        return cls(install.finish(lambda: ca, lambda: CertificateAuthority.load(paths)))

    def trust_anchor(self) -> TrustAnchor:
        """Return this CA's root as the verification set a Display loads."""
        return self._ca.trust_anchor()

    def issue_leaf_certificate(self, csr: CertificateSigningRequest) -> LeafCertificate:
        """Sign *csr* with this CA, returning a leaf chaining to its root."""
        return self._ca.sign_csr(csr)

    def issue_own_leaf(self, hostname: str) -> EnrolledIdentity:
        """Issue the Display's own leaf certificate for *hostname*.

        system.tex step 2 of enrollment: the Display is both the CA and the
        first machine it enrolls, so this collapses the CSR round-trip into
        one local call.
        """
        key_pair, leaf = self._ca.issue_leaf(hostname)
        return EnrolledIdentity(key_pair, leaf)
