"""dial_cross_host -- build a :class:`DisplayLink` over the cross-host mTLS leg.

Kept out of :mod:`display_link` itself so that module need not import
:class:`CrossHostConnector` (the ``AF_UNIX`` client stays free of the TLS
transport it does not use), and out of :mod:`cross_host_connector` so that
module need not import :class:`DisplayLink` (no import cycle). This one small
module is the seam that wires the two together (DES-090 W10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.hub.cross_host_connector import CrossHostConnector
from punt_lux.domain.hub.display_link import DEFAULT_RECV_TIMEOUT, DisplayLink

if TYPE_CHECKING:
    import ssl

__all__ = ["dial_cross_host"]


def dial_cross_host(
    host: str,
    port: int,
    ssl_context: ssl.SSLContext,
    *,
    name: str,
    connect_timeout: float = 5.0,
    recv_timeout: float = DEFAULT_RECV_TIMEOUT,
) -> DisplayLink:
    """Return a :class:`DisplayLink` that dials a remote Display over TCP+mTLS.

    The cross-host leg is always ``kind="hub"`` -- the cross-host listener
    refuses ``kind="test"`` outright (T6) -- and never auto-spawns: a remote
    Display is the user's own process at its configured ``host:port``, never
    one a Hub starts. Once connected, every ``DisplayLink`` method behaves
    exactly as on the ``AF_UNIX`` leg; only the injected dialer differs
    (``system.tex`` §"Connect, cross-host").
    """
    return DisplayLink(
        name=name,
        kind="hub",
        auto_spawn=False,
        connect_timeout=connect_timeout,
        recv_timeout=recv_timeout,
        dialer=CrossHostConnector(
            host=host, port=port, ssl_context=ssl_context, name=name
        ),
    )
