"""OwnerTracker — ``(scene_id, element_id) → Owner`` mapping.

Every Element installed in the Hub records the :class:`Owner` that installed it —
the connection and the identity it declared, snapshotted so a durable board keeps
its repository after the command that made it exits.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["OwnerTracker"]


@final
class OwnerTracker:
    """``(scene_id, element_id) → Owner`` mapping.

    A thin typed wrapper around the owner dict. Holds no other state; every method
    works on the single index.
    """

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
        """Return the recorded owner, or ``None`` if the element is unowned.

        ``None`` is the documented absence contract — the caller decides whether
        absence is fatal (``owner_of``) or benign (the ownership check).
        """
        return self._owners.get((scene_id, element_id))

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop the ownership record. No-op if absent."""
        self._owners.pop((scene_id, element_id), None)

    def keys_for(
        self, connection_id: ConnectionId
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        return tuple(
            key for key, owner in self._owners.items() if owner.owned_by(connection_id)
        )

    def require_ownership(
        self, scene_id: SceneId, element_id: ElementId, attempting: ConnectionId
    ) -> None:
        """Raise ``HubOwnershipError`` if ``attempting`` is not the owner.

        Unknown elements pass silently — the downstream lookup raises
        ``UnknownElementError``, keeping not-found and not-owner distinct.
        """
        owner = self._owners.get((scene_id, element_id))
        if owner is not None:
            owner.ensure_owned_by(attempting, scene_id, element_id)
