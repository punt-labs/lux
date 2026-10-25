"""Ports the display keepalive depends on: a liveness answer, and the clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["KeepaliveClients", "KeepaliveConnection"]


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
class KeepaliveClients(Protocol):
    """Hands out the display connection (reconnecting) and drops an unresponsive one."""

    def asks(self) -> KeepaliveConnection:
        """Reconnect if dropped, and return a connection pinned to the dial in use."""
        ...

    def drop_unresponsive(self, dial: DialRef) -> None:
        """Retire ``dial``, which did not answer, if still current.

        The dial is the display's end, so the next ``asks`` binds afresh and a sender
        still pinned to it is charged to what it sent.
        """
