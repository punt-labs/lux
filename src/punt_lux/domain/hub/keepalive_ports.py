"""Ports the display keepalive depends on: a liveness answer, and the clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["KeepaliveClients", "KeepaliveConnection", "KeepaliveDesk", "KeepaliveLink"]


@runtime_checkable
class KeepaliveConnection(Protocol):
    """What the keepalive needs of a connection: a liveness answer, and its dial."""

    def probe_alive(self, timeout: float) -> bool:
        """Return whether the display is alive, as a liveness check counts it.

        A ping already in flight is itself probing, so a busy dial counts as alive;
        the rule is the connection's, and the keepalive never restates it.
        """
        ...

    @property
    def dial(self) -> DialRef:
        """The dial a probe goes out on: what a failed probe names to drop."""
        ...


@runtime_checkable
class KeepaliveDesk(Protocol):
    """Where the keepalive makes its asks."""

    def asks(self) -> KeepaliveConnection:
        """A connection pinned to the dial that is current now."""
        ...


@runtime_checkable
class KeepaliveLink(Protocol):
    """A display link, seen as the keepalive sees it: the port it pings through."""

    @property
    def desk(self) -> KeepaliveDesk:
        """Where the link's requests are made."""
        ...


@runtime_checkable
class KeepaliveClients(Protocol):
    """Hands out the display connection (reconnecting) and drops a dead one."""

    def get(self) -> KeepaliveLink:
        """Return the connected client, reconnecting and re-registering if dropped."""
        ...

    def drop(self, dial: DialRef) -> None:
        """Retire ``dial`` if still current, so the next ``get`` binds afresh."""
