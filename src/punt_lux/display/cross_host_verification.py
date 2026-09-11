"""CrossHostVerification -- Gate 2: the SAN/HubId hostname cross-check (DES-090 W9).

``ssl.SSLSocket`` is a ``socket.socket`` subtype (system.tex §"Coexistence
with the Local Fast Path"), so Gate 1 -- the mTLS handshake, owned by
``CrossHostListener`` -- has already authenticated *some* certificate by the
time a connection reaches :meth:`ConnectMessage handling
<punt_lux.display.hub_reconciliation.HubReconciliation.handle_connect>`.
Gate 1 alone is not enough: it proves the peer holds a key this Display's
trust anchor signed, not that the ``HubId`` it *declares* in that
``ConnectMessage`` names the machine the certificate was issued to. A
misconfigured -- not even malicious -- Hub could self-report a ``hostname``
colliding with a different, already-live Hub's entry (system.tex
§"Resolving the Trust Fork"). This module closes that gap: it derives the
verified hostname from the peer certificate's own Subject Alternative Name
and rejects the connection outright on any mismatch against the
self-reported ``HubId.hostname`` -- never a degraded-trust fallback
(Invariant 3, system.tex §"Invariants").
"""

from __future__ import annotations

import logging
import socket
import ssl
from typing import Self, final

from punt_lux.domain.identity import HubId
from punt_lux.trust import LeafCertificate

logger = logging.getLogger(__name__)

__all__ = ["CrossHostVerification"]


@final
class CrossHostVerification:
    """Cross-checks a declared ``HubId.hostname`` against the mTLS peer's SAN.

    Structurally scoped to the cross-host leg only: a plain ``socket.socket``
    (the ``AF_UNIX`` case) is never rejected here, so the local socket's own
    ``0700``-permission trust argument stays untouched (Invariant 4) --
    :meth:`reject_unless_verified` returns ``False`` immediately rather than
    reaching for a certificate that connection never presented.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def reject_unless_verified(self, sock: socket.socket, hub_id: HubId) -> bool:
        """Return whether ``sock``'s declared ``hub_id`` must be rejected.

        Comparison is case-insensitive -- DNS names are (RFC 4343) -- via a
        plain ASCII ``str.lower()``, never ``str.casefold()``: casefold is
        Unicode-aware and collides distinct strings (``"faß"`` and
        ``"fass"`` casefold identically), which would let one hostname
        masquerade as another. ``str.lower()`` is exact here because
        ``HubId.hostname`` is already canonicalized ASCII-only at
        construction (``domain/hub_id.py``) and the certificate's SAN is an
        IA5String -- ASCII-only by the X.509 encoding itself (RFC 5280) --
        so only this side, the cert-derived one, still needs lowering. A
        peer certificate this Display cannot read as naming exactly one
        hostname (absent SAN, more than one DNSName, no certificate at all)
        is treated as a mismatch rather than left to raise past this gate:
        fail-closed means every one of those shapes ends in rejection, not a
        crash that could be mistaken for a still-open connection.
        """
        if not isinstance(sock, ssl.SSLSocket):
            return False
        try:
            verified_hostname = self._verified_hostname(sock)
        except Exception as exc:  # noqa: BLE001 -- PY-EH-6: this gate parses a
            # peer's certificate, adversary-influenced DER handed to a
            # third-party library (cryptography/OpenSSL). ANY parse failure
            # -- not just the ValueError this project's own code raises --
            # must reject, never propagate and crash the render loop.
            logger.warning("cross-host peer certificate unusable: %s", exc)
            return True
        mismatch = verified_hostname.lower() != hub_id.hostname
        if mismatch:
            logger.warning(
                "cross-host SAN/hub_id mismatch: cert names %r, hub_id declares %r",
                verified_hostname,
                hub_id.hostname,
            )
        return mismatch

    @staticmethod
    def _verified_hostname(sock: ssl.SSLSocket) -> str:
        """Return the hostname Gate 1's handshake actually verified, or raise.

        A completed ``CERT_REQUIRED`` handshake guarantees a peer
        certificate is present; a ``None`` here would mean this gate ran
        against a not-yet-verified socket, an invariant violation this
        raises loud on rather than silently treating as a hostname.
        """
        der = sock.getpeercert(binary_form=True)
        if der is None:
            msg = "cross-host peer presented no certificate after handshake"
            raise ValueError(msg)
        return LeafCertificate.from_der(der).hostname
