"""RootRemovalRouter — route a scene-root's self-removal back through apply.

``SubtreeInstaller`` registers this class's ``route`` as the observer
callback for a scene-root Element: when a root flips ``_removed``, the store
needs to resolve its owner and run the removal through the normal ``apply``
path, sharing ownership enforcement and storage teardown with every other
removal instead of tearing the index down directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.update import RemoveElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["RootRemovalRouter"]


@final
class RootRemovalRouter:
    """Route an ABC root's self-removal back through the authoritative apply."""

    _owners: OwnerTracker
    _apply: Callable[[ConnectionId, RemoveElement], None]
    __slots__ = ("_apply", "_owners")

    def __new__(
        cls,
        owners: OwnerTracker,
        apply: Callable[[ConnectionId, RemoveElement], None],
    ) -> Self:
        self = super().__new__(cls)
        self._owners = owners
        self._apply = apply
        return self

    def route(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Resolve the root's owner and route its removal through ``apply``.

        An already-forgotten root has no owner and needs no teardown.
        """
        owner = self._owners.get(scene_id, element_id)
        if owner is not None:
            self._apply(
                owner.connection_id,
                RemoveElement(scene_id=scene_id, element_id=element_id),
            )
