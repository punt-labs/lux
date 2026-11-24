"""The Display-specific connection contract registered in the Hub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from punt_lux.hub.peripheral_ports import PeripheralStatus

if TYPE_CHECKING:
    from punt_lux.hub.death_queue import DeathQueue
    from punt_lux.hub.dial_ref import DialRef
    from punt_lux.hub.display_requests import DisplayRequests
    from punt_lux.hub.display_writer import WriteSeat
    from punt_lux.hub.reconnect_signal import ReconnectSignal
    from punt_lux.hub.replicator_ports import DirtyMarker

__all__ = ["DisplayPeripheralPort"]


class DisplayPeripheralPort(PeripheralStatus, Protocol):
    """Connect and reconcile UI through the Display's existing typed ports."""

    def asks(self) -> DisplayRequests:
        """Connect if necessary and pin an ask port to the current dial."""
        ...

    def take_writer(self) -> WriteSeat:
        """Hand over the sole UI writer seat."""
        ...

    def take_deaths(self) -> DeathQueue:
        """Hand over the Display death queue to its sole charger."""
        ...

    def drop(self, dial: DialRef) -> None:
        """Retire a failed dial only if it is still current."""
        ...

    def drop_unresponsive(self, dial: DialRef) -> None:
        """Retire an unresponsive current dial with its attribution intact."""
        ...

    @property
    def reconnects(self) -> ReconnectSignal:
        """Return the wait that paces Display replication."""
        ...

    def attach_replicator(self, marker: DirtyMarker) -> None:
        """Bind the UI dirty marker used after manifest declaration."""
        ...
