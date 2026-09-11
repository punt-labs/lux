"""CertificateAuthority — the personal CA: a root keypair and self-signed cert.

Generated once on the Display's machine (system.tex §"Authentication and
Enrollment", Provider 1); its private key never itself crosses a machine
boundary — only the material it produces, a TrustAnchor or a leaf, does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Self, final

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from punt_lux.trust._facade import _TrustFacade
from punt_lux.trust.certificate_signing_request import CertificateSigningRequest
from punt_lux.trust.key_pair import KeyPair
from punt_lux.trust.leaf_certificate import LeafCertificate
from punt_lux.trust.trust_anchor import TrustAnchor

if TYPE_CHECKING:
    from punt_lux.trust.ca_paths import CaPaths

__all__ = ["CertificateAuthority"]

_DEFAULT_COMMON_NAME = "Lux Personal CA"

# Long-lived root, regenerated only on full re-enrollment, not on a schedule.
_ROOT_VALIDITY = timedelta(days=3650)

# Short-lived leaf, bounding a leaked key's damage window, not a CA rotation.
_LEAF_VALIDITY = timedelta(days=365)

# Backdated so a lagging peer clock still sees a valid cert (ANOTHER host).
_NOT_BEFORE_SKEW = timedelta(minutes=5)

_CA_KEY_USAGE = x509.KeyUsage(
    digital_signature=False,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=True,
    crl_sign=True,
    encipher_only=False,
    decipher_only=False,
)

# key_encipherment omitted: an RSA bit a P-256 TLS 1.3 leaf never needs.
_LEAF_KEY_USAGE = x509.KeyUsage(
    digital_signature=True,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=False,
    crl_sign=False,
    encipher_only=False,
    decipher_only=False,
)


@final
class CertificateAuthority:
    """A self-signed root CA that signs CSRs into DES-090 leaf certificates."""

    _key_pair: KeyPair
    _certificate: x509.Certificate
    __slots__ = ("_certificate", "_key_pair")

    def __new__(cls, key_pair: KeyPair, certificate: x509.Certificate) -> Self:
        _TrustFacade.require_matching_certificate(key_pair, certificate, "root cert")
        self = super().__new__(cls)
        self._key_pair = key_pair
        self._certificate = certificate
        return self

    @classmethod
    def create(cls, common_name: str = _DEFAULT_COMMON_NAME) -> Self:
        """Generate a fresh root keypair and a 10-year self-signed root cert."""
        key_pair = KeyPair.generate()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        now = datetime.now(UTC)
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key_pair.public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _NOT_BEFORE_SKEW)
            .not_valid_after(now + _ROOT_VALIDITY)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(_CA_KEY_USAGE, critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key_pair.public_key),
                critical=False,
            )
        )
        return cls(key_pair, key_pair.sign_certificate_builder(builder))

    @classmethod
    def load(cls, paths: CaPaths) -> Self:
        """Load a previously-saved CA from *paths*, raising on damaged material."""

        def _read() -> tuple[KeyPair, x509.Certificate]:
            key_pair = KeyPair.load(paths.root_key_path)
            cert_pem = paths.root_cert_path.read_bytes()
            return key_pair, x509.load_pem_x509_certificate(cert_pem)

        key_pair, certificate = _TrustFacade.load_or_raise_clearly(paths.dir, _read)
        return cls(key_pair, certificate)

    def save(self, paths: CaPaths) -> None:
        """Persist this CA under *paths*: ``0700`` directory, ``0600`` key."""
        paths.ensure_dir()
        self._key_pair.save(paths.root_key_path)
        paths.root_cert_path.write_bytes(self.certificate_pem())

    def certificate_pem(self) -> bytes:
        """Return the CA's self-signed root certificate as PEM."""
        return self._certificate.public_bytes(encoding=serialization.Encoding.PEM)

    def trust_anchor(self) -> TrustAnchor:
        """Return this CA's root as the verification set a Display loads."""
        return TrustAnchor((self.certificate_pem(),))

    def sign_csr(self, csr: CertificateSigningRequest) -> LeafCertificate:
        """Sign *csr* into a leaf chaining to this CA, rejecting a bad
        signature or non-P-256 key (PY-EH-1) — the CA's key never travels.
        """
        if not csr.is_signature_valid:
            msg = "CSR signature does not verify — refusing to sign"
            raise ValueError(msg)
        hostname = csr.hostname  # raises if SAN is missing/ambiguous
        _TrustFacade.require_p256(csr.public_key)
        now = datetime.now(UTC)
        # A leaf must never outlive the CA that vouches for it.
        root_expiry = self._certificate.not_valid_after_utc
        not_valid_after = min(now + _LEAF_VALIDITY, root_expiry)
        builder = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self._certificate.subject)
            .public_key(csr.public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _NOT_BEFORE_SKEW)
            .not_valid_after(not_valid_after)
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(_LEAF_KEY_USAGE, critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([x509.OID_SERVER_AUTH, x509.OID_CLIENT_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(csr.public_key),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    self._key_pair.public_key
                ),
                critical=False,
            )
        )
        return LeafCertificate(self._key_pair.sign_certificate_builder(builder))

    def issue_leaf(self, hostname: str) -> tuple[KeyPair, LeafCertificate]:
        """Generate a fresh keypair and sign its own leaf for *hostname* —
        requester and CA are the same machine (system.tex step 2), so the
        CSR round-trip that keeps a key from crossing hosts is moot.
        """
        key_pair = KeyPair.generate()
        csr = CertificateSigningRequest.generate(hostname, key_pair)
        return key_pair, self.sign_csr(csr)
