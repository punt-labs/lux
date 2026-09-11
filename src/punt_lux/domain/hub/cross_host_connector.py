"""CrossHostConnector -- the Hub's TCP+mTLS dialer to a remote Display (W10).

The cross-host counterpart to
:class:`~punt_lux.domain.hub.handshake_connector.HandshakeConnector`: it opens
a TCP connection to the Display's configured ``host:port``, wraps it in the
Hub's own ``ssl.SSLContext`` (presenting the Hub's enrolled leaf, verifying the
Display's server leaf against the shared trust anchor), and then runs the
*identical* ``ReadyMessage``/``ConnectMessage`` handshake the local leg runs --
delegated to a composed ``HandshakeConnector`` so the wire sequence lives in
exactly one place (``system.tex`` §"Connect, cross-host": the Hub's connection
code differs only in how it reaches the Display, not in what it sends once
connected). It satisfies the :class:`DisplayDialer` protocol, so ``DisplayLink``
drives it exactly as it drives the ``AF_UNIX`` dialer -- connect, reconnect,
and disconnect map onto the same fd-scoped machinery with no new lifecycle.
"""

from __future__ import annotations

import logging
import socket
import ssl
from typing import Self, final

from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.handshake_outcome import (
    DisplayNotConnectedError,
    HandshakeResult,
)

__all__ = ["CrossHostConnector"]

logger = logging.getLogger(__name__)


@final
class CrossHostConnector:
    """Dials a remote Display over TCP+mTLS, then runs the shared handshake."""

    _host: str
    _port: int
    _ssl_context: ssl.SSLContext
    _handshake: HandshakeConnector
    __slots__ = ("_handshake", "_host", "_port", "_ssl_context")

    def __new__(
        cls, *, host: str, port: int, ssl_context: ssl.SSLContext, name: str
    ) -> Self:
        self = super().__new__(cls)
        self._host = host
        self._port = port
        self._ssl_context = ssl_context
        # Always kind="hub": the cross-host listener refuses kind="test" (T6),
        # so a remote link never declares it. The composed connector supplies
        # the identity and the transport-agnostic Ready/Connect exchange.
        self._handshake = HandshakeConnector(name=name, kind="hub")
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        """Open TCP+mTLS to the remote Display and complete the handshake.

        Raises
        ------
        DisplayNotConnectedError
            If the TCP connection, the TLS handshake (unreachable host,
            untrusted or mismatched certificate), or the
            ``ReadyMessage``/``ConnectMessage`` exchange fails. The socket is
            closed on every failure path -- no half-open connection escapes.
        """
        endpoint = f"{self._host}:{self._port}"
        sock = self._open_tls(connect_timeout, endpoint)
        return self._handshake.complete_handshake(sock, endpoint, connect_timeout)

    def _open_tls(self, connect_timeout: float, endpoint: str) -> ssl.SSLSocket:
        """Return a connected, TLS-verified socket, closing it on any failure."""
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(connect_timeout)
        try:
            tls = self._ssl_context.wrap_socket(raw, server_hostname=self._host)
            tls.connect((self._host, self._port))
        except (OSError, ssl.SSLError) as exc:
            raw.close()
            msg = f"Cannot connect to remote display at {endpoint}: {exc}"
            raise DisplayNotConnectedError(msg) from exc
        tls.settimeout(None)  # hand off a blocking socket, as the local leg does
        return tls
