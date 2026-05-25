"""RootRegistry — ``(scene_id, element_id) → AbcElement`` for scene roots.

Only ABC Elements participate in the property-Observer cascade. The
RootRegistry keeps the strong reference to each scene-root ABC Element
so the disconnect path can flip ``mark_removed`` on every root the
disconnecting connection owned, letting the cascade prune the rest.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["RootRegistry"]


class RootRegistry:
    """``(scene_id, element_id) → AbcElement`` mapping for scene roots."""

    _roots: dict[tuple[SceneId, ElementId], AbcElement]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._roots = {}
        return self

    def register(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        root: AbcElement,
    ) -> None:
        """Register an ABC scene-root for the cascade."""
        self._roots[(scene_id, element_id)] = root

    def get(
        self,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> AbcElement | None:
        """Return the registered ABC root, or ``None`` if absent."""
        return self._roots.get((scene_id, element_id))

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop the registration. No-op if absent."""
        self._roots.pop((scene_id, element_id), None)
