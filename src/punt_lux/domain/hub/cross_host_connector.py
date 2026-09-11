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
from punt_lux.send_timeout import set_send_timeout

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
        self._require_verifying(ssl_context)
        self._host = host
        self._port = port
        self._ssl_context = ssl_context
        # Always kind="hub": the cross-host listener refuses kind="test" (T6),
        # so a remote link never declares it. The composed connector supplies
        # the identity and the transport-agnostic Ready/Connect exchange.
        self._handshake = HandshakeConnector(name=name, kind="hub")
        return self

    @staticmethod
    def _require_verifying(ssl_context: ssl.SSLContext) -> None:
        """Reject a context that would skip verifying the remote Display.

        Fail-closed at construction so no call site can hand this dialer a
        context with ``check_hostname`` off or peer verification disabled --
        the MITM protection is structural, not a property of whoever built the
        context. ``check_hostname`` binds the Display's certificate to the
        ``host`` we dialed; ``CERT_REQUIRED`` makes the Display present one at
        all (system.tex §"Connect, cross-host").
        """
        # verify_mode first: ssl forbids check_hostname=True with CERT_NONE, so a
        # caller lowering verification must clear check_hostname too -- checking
        # verify_mode first names the root downgrade rather than its side effect.
        if ssl_context.verify_mode != ssl.CERT_REQUIRED:
            msg = "cross-host ssl_context must set verify_mode=ssl.CERT_REQUIRED"
            raise ValueError(msg)
        if not ssl_context.check_hostname:
            msg = "cross-host ssl_context must set check_hostname=True"
            raise ValueError(msg)

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
        """Return a connected, TLS-verified socket over the first usable address.

        Resolves ``host`` via ``getaddrinfo`` with ``AF_UNSPEC`` so an IPv6
        Display is reachable as readily as an IPv4 one, trying each address in
        turn. Every failed attempt closes its own socket before moving on (no
        fd leak), and a stalled peer cannot wedge later sends: ``SO_SNDTIMEO``
        bounds them exactly as the ``AF_UNIX`` leg does, on the blocking socket
        handed back.
        """
        try:
            addresses = socket.getaddrinfo(
                self._host, self._port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            msg = f"Cannot resolve remote display at {endpoint}: {exc}"
            raise DisplayNotConnectedError(msg) from exc
        # Reassigned on every failed attempt; getaddrinfo never returns an empty
        # list (it raises instead), so the final raise always carries a real
        # cause, never this sentinel.
        last_exc: OSError = OSError(f"no address resolved for {endpoint}")
        for family, socktype, proto, _canon, sockaddr in addresses:
            raw = socket.socket(family, socktype, proto)
            raw.settimeout(connect_timeout)
            try:
                tls = self._ssl_context.wrap_socket(raw, server_hostname=self._host)
            except (OSError, ssl.SSLError) as exc:
                raw.close()  # wrap never took ownership -- close the raw fd
                last_exc = exc
                continue
            try:
                tls.connect(sockaddr)
            except (OSError, ssl.SSLError) as exc:
                tls.close()  # tls owns raw now -- one close frees the fd
                last_exc = exc
                continue
            set_send_timeout(tls)  # bound sends so a stalled Display can't wedge us
            tls.settimeout(None)  # hand off a blocking socket, as the local leg does
            return tls
        msg = f"Cannot connect to remote display at {endpoint}: {last_exc}"
        raise DisplayNotConnectedError(msg) from last_exc
