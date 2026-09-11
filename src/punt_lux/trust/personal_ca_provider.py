"""PersonalCaProvider — Provider 1, the default trust-anchor provider.

system.tex §"Trust Anchor Providers": free, single-machine key custody,
offline CSR-exchange enrollment. Satisfies TrustAnchorProvider
structurally — no base class, per "families share via Protocol."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.trust._facade import _TrustFacade
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

        A dir with exactly one required file (a save interrupted
        mid-write) raises `load`'s own clear error, not a second CA
        landing beside the first. An atomic-install race loser loads
        the winner's CA; a mid-build error discards the staging dir.
        """
        present = int(paths.root_key_path.exists()) + int(paths.root_cert_path.exists())
        if present > 0:
            return cls(CertificateAuthority.load(paths))
        ca = CertificateAuthority.create()
        install = _TrustFacade.atomic_install(paths.dir)
        install.build(lambda staging: ca.save(CaPaths(staging)))
        return cls(install.finish(lambda: ca, lambda: CertificateAuthority.load(paths)))

    def trust_anchor(self) -> TrustAnchor:
        """Return this CA's root as the verification set a Display loads."""
        return self._ca.trust_anchor()

    def issue_leaf_certificate(self, csr: CertificateSigningRequest) -> LeafCertificate:
        """Sign *csr* with this CA, returning a leaf chaining to its root."""
        return self._ca.sign_csr(csr)

    def issue_own_leaf(self, hostname: str) -> EnrolledIdentity:
        """Issue the Display's own leaf certificate for *hostname* — the
        CSR round-trip collapses to one local call (system.tex step 2).
        """
        key_pair, leaf = self._ca.issue_leaf(hostname)
        return EnrolledIdentity(key_pair, leaf)
