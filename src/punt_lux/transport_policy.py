"""Loopback trust policy for luxd's streamable-HTTP MCP leg.

luxd binds loopback and serves MCP over streamable HTTP beside its REST routes.
One policy is the single source of the loopback allowlist: it decides which
bind hosts luxd will start on, and it projects the same allowlist into the mcp
SDK's ``TransportSecuritySettings`` so the streamable-HTTP transport rejects a
foreign ``Host`` (DNS-rebinding) or ``Origin`` (cross-site) header. Binding and
per-request validation cannot drift because both read this one allowlist.
"""

from __future__ import annotations

from typing import ClassVar, Self, final

from mcp.server.transport_security import TransportSecuritySettings


@final
class LoopbackTransportPolicy:
    """The loopback allowlist that governs luxd's bind and transport guards."""

    _hostnames: tuple[str, ...]

    # Loopback hosts luxd trusts; every guard value below derives from these.
    _DEFAULT_HOSTNAMES: ClassVar[tuple[str, ...]] = ("127.0.0.1", "localhost")

    def __new__(cls, hostnames: tuple[str, ...] = ()) -> Self:
        self = super().__new__(cls)
        self._hostnames = hostnames or cls._DEFAULT_HOSTNAMES
        return self

    def allows_bind_host(self, host: str) -> bool:
        """Return whether luxd may bind ``host``.

        Only a loopback interface is permitted: an off-loopback bind needs
        authentication and a bind-derived origin policy that this unit does not
        carry, so luxd refuses it at startup rather than binding a wider
        interface while the transport guards stay fixed to loopback.
        """
        return host in self._hostnames

    def security_settings(self) -> TransportSecuritySettings:
        """Build the SDK's DNS-rebinding guard for the streamable-HTTP transport.

        Hosts carry a ``:*`` port suffix because luxd always binds an explicit
        port, so the Host header always includes one; origins mirror the
        loopback allowlist across http/https with any port. The transport
        rejects a foreign Host with 421 and a foreign Origin with 403.
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
