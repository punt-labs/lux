"""OwnerTracker — ``(scene_id, element_id) → Owner`` mapping, snapshotted at install."""

from __future__ import annotations

from operator import methodcaller
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["OwnerTracker"]


@final
class OwnerTracker:
    """``(scene_id, element_id) → Owner`` mapping; a thin wrapper, no other state."""

    _owners: dict[tuple[SceneId, ElementId], Owner]
    __slots__ = ("_owners",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._owners = {}
        return self

    def record(self, scene_id: SceneId, element_id: ElementId, owner: Owner) -> None:
        """Record ``owner`` — its connection and declared identity — for the element."""
        self._owners[(scene_id, element_id)] = owner

    def get(self, scene_id: SceneId, element_id: ElementId) -> Owner | None:
        """Return the recorded owner, or ``None`` if unowned — the caller's to judge."""
        return self._owners.get((scene_id, element_id))

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop the ownership record. No-op if absent."""
        self._owners.pop((scene_id, element_id), None)

    def keys_for(
        self, connection_id: ConnectionId
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        owned = methodcaller("owned_by", connection_id)
        return tuple(
            key for key, _ in filter(lambda kv: owned(kv[1]), self._owners.items())
        )

    def release_all(self, connection_id: ConnectionId) -> None:
        """Discard every ownership record this connection holds; vacuous if none."""
        for key in self.keys_for(connection_id):
            self.discard(*key)

    def release_departed(self, connection_ids: Iterable[ConnectionId]) -> None:
        """Release every connection in ``connection_ids``, in one step."""
        for connection_id in connection_ids:
            self.release_all(connection_id)

    def require_ownership(
        self, scene_id: SceneId, element_id: ElementId, attempting: ConnectionId
    ) -> None:
        """Raise ``HubOwnershipError`` if owned by another; unknown/unowned pass."""
        owner = self._owners.get((scene_id, element_id))
        if owner is not None:
            owner.ensure_owned_by(attempting, scene_id, element_id)
