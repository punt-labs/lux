"""OwnerTracker — ``(scene_id, element_id) → ConnectionId`` mapping.

Every Element installed in the Hub carries the ``ConnectionId`` that
installed it. The owner is what ``Display.interact`` gates on and what
the disconnect cleanup walks to find each connection-owned root.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["OwnerTracker"]


class OwnerTracker:
    """``(scene_id, element_id) → ConnectionId`` mapping.

    A thin typed wrapper around the owner dict. Holds no other state;
    every method works on the single index.
    """

    _owners: dict[tuple[SceneId, ElementId], ConnectionId]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._owners = {}
        return self

    def record(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        owner: ConnectionId,
    ) -> None:
        """Record ``owner`` as the installer of the element."""
        self._owners[(scene_id, element_id)] = owner

    def get(self, scene_id: SceneId, element_id: ElementId) -> ConnectionId | None:
        """Return the recorded owner, or ``None`` if the element is unowned."""
        return self._owners.get((scene_id, element_id))

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop the ownership record. No-op if absent."""
        self._owners.pop((scene_id, element_id), None)

    def keys_for(
        self,
        connection_id: ConnectionId,
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        return tuple(
            key for key, owner in self._owners.items() if owner == connection_id
        )
