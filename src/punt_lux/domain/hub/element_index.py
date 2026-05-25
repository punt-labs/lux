"""ElementIndex — ``(scene_id, element_id) → Element`` lookup table.

The Hub-side ``O(1)`` index of every installed Element. Scoped per
scene; a missing scene and a missing element raise distinct lookup
errors so the caller can distinguish ``unknown scene`` from
``element not in scene``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["ElementIndex", "UnknownElementError", "UnknownSceneError"]


@dataclass(frozen=True, slots=True)
class UnknownSceneError(LookupError):
    """Raised when ``lookup`` targets a scene that has never been added."""

    scene_id: SceneId

    def __str__(self) -> str:
        return f"unknown scene: {self.scene_id!r}"


@dataclass(frozen=True, slots=True)
class UnknownElementError(LookupError):
    """Raised when ``lookup`` targets an element that is not in the index."""

    scene_id: SceneId
    element_id: ElementId

    def __str__(self) -> str:
        return f"unknown element: {self.element_id!r} in scene {self.scene_id!r}"


class ElementIndex:
    """``(scene_id, element_id) → Element`` mapping.

    Holds the per-scene element store. ``install_root`` opens a scene
    bucket; ``install_child`` appends into an existing scene; ``lookup``
    returns the indexed Element or raises a typed lookup error.
    """

    _by_scene: dict[SceneId, dict[ElementId, WireElement]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = {}
        return self

    def install_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        element: WireElement,
    ) -> None:
        """Install ``element`` as a scene-root under ``scene_id``."""
        scene = self._by_scene.setdefault(scene_id, {})
        scene[element_id] = element

    def install_child(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        element_id: ElementId,
        element: WireElement,
    ) -> None:
        """Install ``element`` under ``parent_id``.

        Raises ``UnknownSceneError`` if the scene is unknown and
        ``UnknownElementError`` if ``parent_id`` is not yet indexed.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        if parent_id not in scene:
            raise UnknownElementError(scene_id=scene_id, element_id=parent_id)
        scene[element_id] = element

    def lookup(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise the matching lookup error."""
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        element = scene.get(element_id)
        if element is None:
            raise UnknownElementError(scene_id=scene_id, element_id=element_id)
        return element

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Remove an indexed element. No-op if absent.

        Index-side cleanup only. The Observer cascade is responsible for
        unwinding parent composites; this method clears the storage so
        future ``lookup`` calls fail loud.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None or element_id not in scene:
            return
        del scene[element_id]
