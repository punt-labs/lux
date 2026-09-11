"""AwsPrivateCaProvider — Provider 2, AWS Private CA (managed), DES-090.

system.tex §"Provider 2 (Optional): AWS Private CA (Managed)": an opt-in
alternative to Provider 1 (:class:`.personal_ca_provider.PersonalCaProvider`)
for an adopter who already operates AWS infrastructure and wants managed
issuance and revocation instead of self-managed key custody. Satisfies
:class:`.provider.TrustAnchorProvider` structurally — no base class, per
"families share via Protocol" — with the identical two obligations Provider
1 answers: return the trust anchor a Display's ``ssl.SSLContext`` verifies
against, and sign a CSR into a leaf chaining to it. The CA's own private key
never enters this process; it lives inside ACM Private CA, gated by whatever
IAM policy the operator attached to the calling principal.

Credentials come from boto3's default provider chain (environment, shared
config, an attached IAM role, IAM Roles Anywhere, or an active SSO session)
— this class never accepts, stores, or forwards a static access key, per
the org's no-long-lived-IAM-keys standard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Self, cast, final

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from punt_lux.trust.leaf_certificate import LeafCertificate
from punt_lux.trust.trust_anchor import TrustAnchor

if TYPE_CHECKING:
    from punt_lux.trust._acm_pca_client import _AcmPcaClient, _Boto3Module
    from punt_lux.trust.aws_private_ca_config import AwsPrivateCaConfig
    from punt_lux.trust.certificate_signing_request import CertificateSigningRequest

__all__ = ["AwsPrivateCaProvider"]

_CERTIFICATE_ISSUED_WAITER: Literal["certificate_issued"] = "certificate_issued"


@final
class AwsPrivateCaProvider:
    """A managed ACM Private CA, wrapped as a trust-anchor provider."""

    _config: AwsPrivateCaConfig
    _client: _AcmPcaClient
    __slots__ = ("_client", "_config")

    def __new__(cls, config: AwsPrivateCaConfig, client: _AcmPcaClient) -> Self:
        self = super().__new__(cls)
        self._config = config
        self._client = client
        return self

    @classmethod
    def connect(cls, config: AwsPrivateCaConfig) -> Self:
        """Build a provider backed by a real ``boto3`` ACM Private CA client.

        The client's region is taken from the CA ARN in *config*, not boto3's
        ambient default (env/shared-config/IMDS): the ACM Private CA client
        must reach the region the CA lives in, and a client silently pointed
        elsewhere fails confusingly against a CA that "does not exist" there.

        Resolves credentials from boto3's default chain — never a static
        key this class holds or accepts. ``boto3`` is an opt-in dependency
        (the ``aws`` extra); importing it here, inside the one factory that
        needs it, keeps a base ``punt-lux`` install free of it (PL-PA-4).
        """
        import boto3  # noqa: PLC0415 — optional heavy dep, see module docstring

        # boto3 generates its client classes at runtime from AWS's service
        # model, so it ships no stubs for pyright/mypy to check against.
        # Casting the module itself onto the one member this call needs
        # (_Boto3Module) resolves every downstream type from a single typed
        # boundary instead of a suppression at the call site (PY-TS-12).
        client_factory = cast("_Boto3Module", boto3)
        raw_client = client_factory.client("acm-pca", region_name=config.region)
        client = cast("_AcmPcaClient", raw_client)
        return cls(config, client)

    def trust_anchor(self) -> TrustAnchor:
        """Return the CA's own certificate chain as the verification set a
        Display loads — root plus any intermediate ACM Private CA reports.
        """
        response = self._ca_certificate_response()
        bundle = response["Certificate"].encode("ascii")
        # Absent for a root CA with no subordinate above it — the documented
        # shape of GetCertificateAuthorityCertificate's response, not a
        # failure to check for (PY-TS-14).
        chain = response.get("CertificateChain")
        if chain:
            bundle += b"\n" + chain.encode("ascii")
        return TrustAnchor(self._split_pem_bundle(bundle))

    def issue_leaf_certificate(self, csr: CertificateSigningRequest) -> LeafCertificate:
        """Sign *csr* via ACM Private CA issuance, returning a leaf chaining
        to this provider's CA.

        Runs the identical pre-issuance checks
        :meth:`.certificate_authority.CertificateAuthority.sign_csr` runs
        before Provider 1 signs locally — a CSR whose self-signature does
        not verify, or whose SAN is missing or ambiguous, is rejected before
        it ever reaches AWS, never silently forwarded as an API call AWS
        would have to reject on Lux's behalf. The requested validity is also
        clamped to the CA's own remaining lifetime — the identical rule
        :meth:`.certificate_authority.CertificateAuthority.sign_csr` applies
        locally for Provider 1 (a leaf must never outlive the CA vouching for
        it), computed here from ACM Private CA's own reported expiry rather
        than an in-memory certificate.
        """
        if not csr.is_signature_valid:
            msg = "CSR signature does not verify — refusing to submit for issuance"
            raise ValueError(msg)
        _ = csr.hostname  # raises unless the SAN names exactly one hostname

        not_valid_after = self._clamped_leaf_expiry()
        issued = self._client.issue_certificate(
            CertificateAuthorityArn=self._config.ca_authority_arn,
            Csr=csr.to_pem(),
            SigningAlgorithm=self._config.signing_algorithm,
            TemplateArn=self._config.template_arn,
            Validity={"Value": int(not_valid_after.timestamp()), "Type": "ABSOLUTE"},
        )
        certificate_arn = issued["CertificateArn"]
        # ACM Private CA issuance is asynchronous — the waiter blocks (with
        # boto3's own bounded polling/backoff) until the certificate is
        # ready, or raises on timeout/failure, rather than this class
        # inventing its own retry loop atop a raw GetCertificate poll.
        self._client.get_waiter(_CERTIFICATE_ISSUED_WAITER).wait(
            CertificateAuthorityArn=self._config.ca_authority_arn,
            CertificateArn=certificate_arn,
        )
        issued_certificate = self._client.get_certificate(
            CertificateAuthorityArn=self._config.ca_authority_arn,
            CertificateArn=certificate_arn,
        )
        return LeafCertificate.from_pem(
            issued_certificate["Certificate"].encode("ascii")
        )

    def _ca_certificate_response(self) -> dict[str, str]:
        """Return ACM Private CA's own ``GetCertificateAuthorityCertificate``
        response — the one AWS call both :meth:`trust_anchor` and
        :meth:`_clamped_leaf_expiry` read from, kept in one place rather than
        duplicated at each call site.
        """
        return self._client.get_certificate_authority_certificate(
            CertificateAuthorityArn=self._config.ca_authority_arn,
        )

    def _clamped_leaf_expiry(self) -> datetime:
        """Return the leaf's ``not_valid_after``, clamped to the CA's own
        remaining lifetime — a leaf must never outlive the CA that vouches
        for it, mirroring :meth:`.certificate_authority.CertificateAuthority
        .sign_csr`'s identical ``min(now + validity, root_expiry)`` clamp.

        A CA at or past its own expiry has no window left to clamp to: the
        clamp would produce a ``not_valid_after`` in the past, which ACM
        Private CA rejects with an opaque ``IssueCertificate`` error. Fail
        loud here instead, naming the CA's expiry, so the operator knows to
        renew or replace the CA rather than debug an AWS-side rejection.
        """
        now = datetime.now(UTC)
        requested = now + timedelta(days=self._config.validity_days)
        ca_certificate = x509.load_pem_x509_certificate(
            self._ca_certificate_response()["Certificate"].encode("ascii")
        )
        ca_expiry = ca_certificate.not_valid_after_utc
        not_valid_after = min(requested, ca_expiry)
        if not_valid_after <= now:
            msg = (
                "ACM Private CA has no remaining validity to issue a leaf: the "
                f"CA expires at {ca_expiry.isoformat()} (now {now.isoformat()}). "
                "Renew or replace the CA before issuing certificates."
            )
            raise ValueError(msg)
        return not_valid_after

    @staticmethod
    def _split_pem_bundle(bundle: bytes) -> tuple[bytes, ...]:
        """Split a concatenated PEM chain into one PEM block per certificate.

        ``TrustAnchor`` wants one certificate per entry; ACM Private CA's
        ``GetCertificateAuthorityCertificate`` returns a single concatenated
        PEM string covering the root plus any intermediates.
        """
        certificates = x509.load_pem_x509_certificates(bundle)
        return tuple(
            certificate.public_bytes(serialization.Encoding.PEM)
            for certificate in certificates
        )
