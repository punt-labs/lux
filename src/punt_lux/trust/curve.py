"""P-256 (SECP256R1) curve enforcement, shared by every EC key and CSR this
package holds (DES-090). Both KeyPair and CertificateSigningRequest funnel
every construction and load path through here, so a hand-crafted P-384 or
P-521 PEM is rejected before either class ever holds it.
"""

from __future__ import annotations

from typing import TypeVar

from cryptography.hazmat.primitives.asymmetric import ec

__all__ = ["Curve"]

_EllipticKey = TypeVar(
    "_EllipticKey", ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey
)


class Curve:
    """The one curve this project's trust material is built to hold."""

    @staticmethod
    def require_p256(key: _EllipticKey) -> _EllipticKey:
        """Return *key* unchanged, or raise if it is not curve P-256."""
        if not isinstance(key.curve, ec.SECP256R1):
            msg = f"expected SECP256R1 (P-256), got {key.curve.name}"
            raise ValueError(msg)
        return key
