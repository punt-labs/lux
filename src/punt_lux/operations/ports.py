"""Hub collaborators the operations layer is given at construction, via HubPorts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.hub_collaborators import InboxDepth

__all__ = ["DirtyMarker", "ElementFactoryFor", "EnsureWriter", "HubPorts", "NextEvent"]

# A connection-scoped element decoder — one factory per calling session.
type ElementFactoryFor = Callable[[ConnectionId], JsonElementFactory]
# Bind the session's inbox writer; idempotent.
type EnsureWriter = Callable[[ConnectionId], None]
# Take the next queued business event, or ``None`` when the inbox is empty.
type NextEvent = Callable[[ConnectionId, float], ObserverMessage | None]


@runtime_checkable
class DirtyMarker(Protocol):
    """The signals a Hub write sends the background replicator."""

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Record a changed scene so the replicator resends it."""

    def mark_menus(self) -> None:
        """Flag that the menu registry changed so the replicator re-reads and pushes."""


@dataclass(frozen=True, slots=True)
class HubPorts:
    """The presentation-provided Hub collaborators the concern classes compose."""

    element_factory: ElementFactoryFor
    ensure_writer: EnsureWriter
    next_event: NextEvent
    inbox_depth: InboxDepth
    display_port: DisplayPort
