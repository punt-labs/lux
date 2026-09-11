"""CrossHostEndpoint -- a remote Display's dialable address (DES-090 W10).

Kept out of :mod:`display_link` so that module need not import
:class:`CrossHostConnector` (the ``AF_UNIX`` client stays free of the TLS
transport it does not use), and out of :mod:`cross_host_connector` so that
module need not import :class:`DisplayLink` (no import cycle). This one small
value class is the seam that wires the two together: it holds where and how to
reach a remote Display, and :meth:`dial` builds the :class:`DisplayLink` that
speaks to it over the cross-host mTLS leg.
"""

from __future__ import annotations

import ssl
from typing import Self, final

from punt_lux.domain.hub.cross_host_connector import CrossHostConnector
from punt_lux.domain.hub.display_link import DEFAULT_RECV_TIMEOUT, DisplayLink

__all__ = ["CrossHostEndpoint"]


@final
class CrossHostEndpoint:
    """A remote Display's ``host:port`` plus the Hub's own mTLS context."""

    _host: str
    _port: int
    _ssl_context: ssl.SSLContext
    __slots__ = ("_host", "_port", "_ssl_context")

    def __new__(cls, host: str, port: int, ssl_context: ssl.SSLContext) -> Self:
        self = super().__new__(cls)
        self._host = host
        self._port = port
        self._ssl_context = ssl_context
        return self

    def dial(
        self,
        *,
        name: str,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
    ) -> DisplayLink:
        """Return a :class:`DisplayLink` that dials this Display over TCP+mTLS.

        The cross-host leg is always ``kind="hub"`` -- the cross-host listener
        refuses ``kind="test"`` outright (T6) -- and never auto-spawns: a
        remote Display is the user's own process, never one a Hub starts. Once
        connected, every ``DisplayLink`` method behaves exactly as on the
        ``AF_UNIX`` leg; only the injected dialer differs (``system.tex``
        §"Connect, cross-host").
        """
        return DisplayLink(
            name=name,
            kind="hub",
            auto_spawn=False,
            connect_timeout=connect_timeout,
            recv_timeout=recv_timeout,
            dialer=CrossHostConnector(
                host=self._host,
                port=self._port,
                ssl_context=self._ssl_context,
                name=name,
            ),
        )
