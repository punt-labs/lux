"""_TrustFacade — the one internal edge trust/ consumers take for the shared
boundary-check primitives, instead of a direct edge to each (PL-CU-1).

Curve, Pairing, MaterialLoad, and AtomicDirInstall are four small,
single-purpose classes (PY-OO-7, PY-IC-6) — splitting them stays correct
design. But a consumer that needs several of them (CertificateAuthority
needs three) pays one efferent-coupling edge per import, and the ratchet
counts distinct internal modules, not distinct concepts. This mediator is
the fix PL-CU-1 itself prescribes: "extract a facade or mediator that the
module imports instead of importing each dependency directly." Every
method here is a thin pass-through — the real logic still lives on Curve,
Pairing, MaterialLoad, and AtomicDirInstall; this class only concentrates
the *edges* to them into one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from cryptography.hazmat.primitives.asymmetric import ec

from punt_lux.trust.atomic_dir_install import AtomicDirInstall
from punt_lux.trust.curve import Curve
from punt_lux.trust.key_pairing import Pairing
from punt_lux.trust.material_load import MaterialLoad

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from cryptography import x509

    from punt_lux.trust.key_pairing import KeyedByPublicKeyPem

__all__ = ["_TrustFacade"]

# Mirrors Curve's own constraint (curve.py) — a TypeVar can't be imported and
# reused across modules for its constraint, only redeclared identically.
_EllipticKey = TypeVar(
    "_EllipticKey", ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey
)
_T = TypeVar("_T")


class _TrustFacade:
    """Namespace mediating every trust/ boundary-check primitive."""

    @staticmethod
    def require_p256(key: _EllipticKey) -> _EllipticKey:
        """Return *key* unchanged, or raise if it is not curve P-256."""
        return Curve.require_p256(key)

    @staticmethod
    def require_matching(
        a: KeyedByPublicKeyPem, b: KeyedByPublicKeyPem, what: str
    ) -> None:
        """Raise :class:`ValueError` naming *what* unless *a* and *b*
        report the same public key.
        """
        Pairing.require_matching(a, b, what)

    @staticmethod
    def require_matching_certificate(
        key_pair: KeyedByPublicKeyPem, certificate: x509.Certificate, what: str
    ) -> None:
        """Raise :class:`ValueError` naming *what* unless *key_pair* and
        *certificate* share a public key.
        """
        Pairing.require_matching_certificate(key_pair, certificate, what)

    @staticmethod
    def load_or_raise_clearly(directory: Path, load: Callable[[], _T]) -> _T:
        """Call *load*, or raise naming *directory* on a damaged result."""
        return MaterialLoad.or_raise_clearly(directory, load)

    @staticmethod
    def atomic_install(dest: Path) -> AtomicDirInstall:
        """Return a fresh :class:`AtomicDirInstall` staging *dest*."""
        return AtomicDirInstall(dest)
