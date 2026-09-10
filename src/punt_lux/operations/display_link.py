"""DisplayLinkOperations — report the Hub's observed display-link state.

Pure classification: no round-trip to the display, only the local facts the
Hub already holds — the connection's live/dead state, the replicator's
pending retry delay, and the store's live-scene count — so a caller learns
the link state even while the display is unreachable (design §6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.display_linkage import DisplayLinkage
from punt_lux.operations.models.display_link import (
    ConnectedLinkState,
    DisconnectedLinkState,
    DisplayLinkState,
)
from punt_lux.operations.ports import DirtyMarker

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.display_port import DisplayPort

__all__ = ["DisplayLinkOperations", "ReplicatorLink"]


@runtime_checkable
class ReplicatorLink(DirtyMarker, Protocol):
    """``DirtyMarker`` plus the pending not-connected retry delay, in seconds."""

    @property
    def disconnected_delay(self) -> float: ...


@final
class DisplayLinkOperations:
    """Classify the Hub's display link from local state only — no round-trip."""

    _display_port: DisplayPort
    _display: HubDisplay
    _replicator: ReplicatorLink
    __slots__ = ("_display", "_display_port", "_replicator")

    def __new__(
        cls,
        display_port: DisplayPort,
        display: HubDisplay,
        replicator: ReplicatorLink,
    ) -> Self:
        self = super().__new__(cls)
        self._display_port = display_port
        self._display = display
        self._replicator = replicator
        return self

    def get_link(self) -> DisplayLinkState:
        """Return the connected/disconnected link state; this never faults."""
        linkage = DisplayLinkage.classify(
            connected=self._display_port.is_connected,
            live_scene_count=len(self._display.live_scene_ids()),
        )
        if linkage is DisplayLinkage.CONNECTED_ACTIVE:
            return ConnectedLinkState(linkage="connected_active")
        if linkage is DisplayLinkage.CONNECTED_IDLE:
            return ConnectedLinkState(linkage="connected_idle")
        tag: Literal["held", "disconnected"] = (
            "held" if linkage is DisplayLinkage.HELD else "disconnected"
        )
        return DisconnectedLinkState(
            linkage=tag, retry_delay_seconds=self._replicator.disconnected_delay
        )
