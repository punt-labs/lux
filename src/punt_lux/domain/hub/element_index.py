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

    Roots and children share one per-scene ``element_id → Element`` store
    so ``lookup`` reaches a buried child by id. A parallel per-scene
    insertion-ordered set of root ids remembers which of those entries are
    scene roots, so ``scene_roots`` returns exactly the top level. Without
    it, a re-push built from ``scene_roots`` would hoist every child to a
    sibling of its own container and duplicate it against the in-tree copy.
    """

    _by_scene: dict[SceneId, dict[ElementId, WireElement]]
    _roots_by_scene: dict[SceneId, dict[ElementId, None]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = {}
        self._roots_by_scene = {}
        return self

    def install_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        element: WireElement,
    ) -> None:
        """Install ``element`` as a scene-root under ``scene_id``."""
        self._by_scene.setdefault(scene_id, {})[element_id] = element
        self._roots_by_scene.setdefault(scene_id, {})[element_id] = None

    def install_child(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        element: WireElement,
    ) -> None:
        """Install ``element`` under ``parent_id``, keyed by its own ``id``.

        Raises ``UnknownSceneError`` if the scene is unknown and
        ``UnknownElementError`` if ``parent_id`` is not yet indexed. The
        child lands in the shared per-scene store for ``lookup`` but is
        never recorded as a root — ``scene_roots`` stays the top level.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        if parent_id not in scene:
            raise UnknownElementError(scene_id=scene_id, element_id=parent_id)
        scene[ElementId(element.id)] = element

    def lookup(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise the matching lookup error."""
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        element = scene.get(element_id)
        if element is None:
            raise UnknownElementError(scene_id=scene_id, element_id=element_id)
        return element

    def contains(self, scene_id: SceneId, element_id: ElementId) -> bool:
        """Return whether ``element_id`` is installed — ``lookup`` without a raise."""
        scene = self._by_scene.get(scene_id)
        return scene is not None and element_id in scene

    def scene_roots(self, scene_id: SceneId) -> list[WireElement]:
        """Return the scene's root elements in install order (non-removed only).

        Only elements installed via ``install_root`` are returned; children
        installed via ``install_child`` share the store for ``lookup`` but
        are never roots. Returning children here would flatten the tree on a
        re-push — each child hoisted to a top-level sibling and duplicated
        against its in-tree copy.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None:
            return []
        return [
            elem
            for element_id in self._roots_by_scene.get(scene_id, {})
            if (elem := scene.get(element_id)) is not None
            and not self._is_removed(elem)
        ]

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Remove an indexed element. No-op if absent.

        Index-side cleanup only. The Observer cascade is responsible for
        unwinding parent composites; this method clears the storage so
        future ``lookup`` calls fail loud. A discarded root also leaves the
        scene's root set so it stops appearing in ``scene_roots``.
        """
        if not self.contains(scene_id, element_id):
            return
        del self._by_scene[scene_id][element_id]
        self._roots_by_scene.get(scene_id, {}).pop(element_id, None)

    @staticmethod
    def _is_removed(elem: WireElement) -> bool:
        """Return True if ``elem`` is an ABC element flagged removed.

        Legacy wire dataclasses have no lifecycle flag and are never removed;
        only migrated ABC elements carry ``removed``. The ABC type is imported
        lazily to avoid a circular import with ``element_abc``.
        """
        from punt_lux.domain.element_abc import Element as ElementABC

        return isinstance(elem, ElementABC) and elem.removed
