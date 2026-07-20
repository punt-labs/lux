"""Loopback trust policy for the luxd WebSocket transport.

luxd guards its ``/mcp`` handshake twice: it rejects a browser ``Origin`` whose
host is not loopback before the upgrade, and it hands the mcp SDK a
``TransportSecuritySettings`` that repeats the check on the Host and Origin
headers at the transport itself. Both guards must agree on which hosts are
trusted; deriving both from this one policy keeps them from drifting apart.
"""

from __future__ import annotations

from typing import ClassVar, Self, final
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings


@final
class LoopbackTransportPolicy:
    """The loopback allowlist that backs both luxd WebSocket handshake guards."""

    _hostnames: tuple[str, ...]

    # Loopback hosts luxd trusts; every guard value below derives from these.
    _DEFAULT_HOSTNAMES: ClassVar[tuple[str, ...]] = ("127.0.0.1", "localhost")

    def __new__(cls, hostnames: tuple[str, ...] = ()) -> Self:
        self = super().__new__(cls)
        self._hostnames = hostnames or cls._DEFAULT_HOSTNAMES
        return self

    def rejects_origin(self, origin: str | None) -> bool:
        """Return whether a WebSocket ``Origin`` should be rejected (CSWSH guard).

        Browsers always send an ``Origin`` on a WebSocket upgrade; non-browser
        clients such as mcp-proxy send none, so an absent origin is allowed. A
        present origin is allowed only when its host is one of the loopback
        names — this is what keeps a cross-site page from hijacking the socket.
        """
        if origin is None:
            return False
        return urlparse(origin).hostname not in self._hostnames

    def security_settings(self) -> TransportSecuritySettings:
        """Build the SDK's DNS-rebinding guard for the handshake.

        Hosts carry a ``:*`` port suffix because luxd always binds an explicit
        port, so the Host header always includes one; origins mirror the
        loopback allowlist across http/https with any port.
        """
        return TransportSecuritySettings(
            allowed_hosts=[f"{host}:*" for host in self._hostnames],
            allowed_origins=[
                f"{scheme}://{host}{suffix}"
                for host in self._hostnames
                for scheme in ("http", "https")
                for suffix in ("", ":*")
            ],
        )
