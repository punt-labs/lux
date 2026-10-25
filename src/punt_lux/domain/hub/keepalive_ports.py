"""Ports the display keepalive depends on: a ping round-trip, and the clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import PongMessage

__all__ = ["KeepaliveClients", "KeepaliveConnection", "KeepaliveLink"]


@runtime_checkable
class KeepaliveConnection(Protocol):
    """The one capability the keepalive needs of a connection: a ping round-trip."""

    def ping(self, timeout: float | None = ...) -> PongMessage | None:
        """Send a ping and return the pong, or ``None`` if none arrived in time.

        Raises :class:`~punt_lux.domain.hub.display_busy.DisplayBusyError` when
        another ping held the dial for the whole wait and nothing was sent.
        """
        ...

    @property
    def dial(self) -> DialGeneration:
        """The dial a ping goes out on: what a failed probe names to drop."""
        ...


@runtime_checkable
class KeepaliveLink(Protocol):
    """A display link, seen as the keepalive sees it: the port it pings through."""

    @property
    def requests(self) -> KeepaliveConnection:
        """The link's outbound port."""
        ...


@runtime_checkable
class KeepaliveClients(Protocol):
    """Hands out the display connection (reconnecting) and drops a dead one."""

    def get(self) -> KeepaliveLink:
        """Return the connected client, reconnecting and re-registering if dropped."""
        ...

    def drop(self, generation: DialGeneration) -> None:
        """Retire ``generation`` if still current, so the next ``get`` binds afresh."""
