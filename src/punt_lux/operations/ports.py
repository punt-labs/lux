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

__all__ = [
    "DirtyMarker",
    "ElementFactoryFor",
    "EnsureWriter",
    "HubPorts",
    "InboxDepth",
    "NextEvent",
]

# Per-connection Hub collaborators: decode an element, bind a writer, drain one
# event, and read the queued-but-undelivered count (observational only).
type ElementFactoryFor = Callable[[ConnectionId], JsonElementFactory]
type EnsureWriter = Callable[[ConnectionId], None]
type NextEvent = Callable[[ConnectionId, float], ObserverMessage | None]
type InboxDepth = Callable[[ConnectionId], int]


@runtime_checkable
class DirtyMarker(Protocol):
    """The signals a Hub write sends the background replicator."""

    def mark_dirty(self, scene_id: SceneId) -> None: ...
    def mark_menus(self) -> None: ...


@dataclass(frozen=True, slots=True)
class HubPorts:
    element_factory: ElementFactoryFor
    ensure_writer: EnsureWriter
    next_event: NextEvent
    inbox_depth: InboxDepth
    display_port: DisplayPort
