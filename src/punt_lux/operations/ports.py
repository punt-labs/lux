"""The Hub collaborators the operations layer is given at construction.

The operations layer is pure engine core: it imports domain state, never the
MCP transport. Two Hub-side helpers it needs — connection-scoped element decode
and the session inbox — currently live under ``tools/`` as free functions. The
presentation layer wires them in as :class:`HubPorts` so nothing in
``operations/`` reaches back up into ``tools/``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId

__all__ = ["DirtyMarker", "ElementFactoryFor", "EnsureWriter", "HubPorts", "NextEvent"]

# A connection-scoped element decoder — one factory per calling session so a
# decoded element's publish sink lands on that session's topics.
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

    def mark_cleared(self) -> None:
        """Record that the whole display was blanked."""

    def mark_menus(
        self,
        bar: Sequence[Mapping[str, object]],
        items: Sequence[Mapping[str, object]],
    ) -> None:
        """Record new menu state (bar + tool items) so the replicator pushes it."""


@dataclass(frozen=True, slots=True)
class HubPorts:
    """The presentation-provided Hub helpers the concern classes compose."""

    element_factory: ElementFactoryFor
    ensure_writer: EnsureWriter
    next_event: NextEvent
