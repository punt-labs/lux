"""ElementIndex — ``(scene_id, element_id) → Element`` lookup table.

The Hub-side ``O(1)`` index of every installed Element. Scoped per
scene; a missing scene and a missing element raise distinct lookup
errors so the caller can distinguish ``unknown scene`` from
``element not in scene``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from punt_lux.domain.element import Element as WireElement
from punt_lux.domain.element_identity import ElementIdentity
from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["ElementIndex", "UnknownElementError", "UnknownSceneError"]

# Anonymous elements (empty id) carry no name to key on and several may repeat
# in one scene, so each is stored under a synthesized handle from this reserved
# namespace and never overwrites another. The leading NUL cannot collide with a
# realistic agent-supplied id (``ElementId`` is an unvalidated ``NewType(str)``).
_ANON_KEY_PREFIX = "\x00lux-anon:"


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


@final
class ElementIndex:
    """``(scene_id, element_id) → Element`` mapping.

    Holds the per-scene element store: ``install_root`` and ``install_child``
    write, ``lookup`` reads or raises a typed lookup error.

    Roots and children share one per-scene store so ``lookup`` reaches a
    buried child by key; a parallel insertion-ordered set of root keys
    remembers which entries are roots, so ``scene_roots`` returns exactly
    the top level without hoisting children to siblings on a re-push. A
    named element keys on its own id, an anonymous one on a synthesized
    handle; every install returns the key it assigned so the Hub's parallel
    maps track the same handle.
    """

    _by_scene: dict[SceneId, dict[ElementId, WireElement]]
    _roots_by_scene: dict[SceneId, dict[ElementId, None]]
    _anon_seq: int
    __slots__ = ("_anon_seq", "_by_scene", "_roots_by_scene")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = {}
        self._roots_by_scene = {}
        self._anon_seq = 0
        return self

    def install_root(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        element: WireElement,
    ) -> ElementId:
        """Install ``element`` as a scene-root; return the key it was stored under.

        An anonymous element keys on a fresh synthesized handle so repeated
        anonymous roots never collide.
        """
        key = self._allocate_key(element_id, element)
        self._by_scene.setdefault(scene_id, {})[key] = element
        self._roots_by_scene.setdefault(scene_id, {})[key] = None
        return key

    def install_child(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        element: WireElement,
    ) -> ElementId:
        """Install ``element`` under ``parent_id``; return the key it was stored under.

        Raises ``UnknownSceneError`` if the scene is unknown and
        ``UnknownElementError`` if ``parent_id`` is not yet indexed. An
        anonymous child keys on a fresh synthesized handle so repeats never
        collide; it lands in the shared store for ``lookup`` but is never a root.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        if parent_id not in scene:
            raise UnknownElementError(scene_id=scene_id, element_id=parent_id)
        key = self._allocate_key(ElementId(element.id), element)
        scene[key] = element
        return key

    def _allocate_key(self, element_id: ElementId, element: WireElement) -> ElementId:
        """Return the store key for ``element`` — its id, or a fresh anon handle.

        An anonymous element keys on a per-index-unique handle from the
        reserved namespace, so two in one scene never share a slot.
        """
        if not ElementIdentity.of(element).is_anonymous:
            return element_id
        key = ElementId(f"{_ANON_KEY_PREFIX}{self._anon_seq}")
        self._anon_seq += 1
        return key

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

        Only ``install_root`` entries are returned; children share the store
        for ``lookup`` but never appear here, so a re-push cannot flatten the
        tree by hoisting a child to a top-level sibling.
        """
        return [elem for _key, elem in self.scene_root_items(scene_id)]

    def scene_root_items(
        self, scene_id: SceneId
    ) -> list[tuple[ElementId, WireElement]]:
        """Return each root's store key paired with its element, in install order.

        ``ChildIndex`` keys parent → child edges by the store handle, so a
        caller resolving a root's descendants must use the key, not the wire
        id: an anonymous composite root carries ``id == ""`` while its child
        edges live under the synth handle.
        """
        scene = self._by_scene.get(scene_id)
        if scene is None:
            return []
        return [
            (key, elem)
            for key in self._roots_by_scene.get(scene_id, {})
            if (elem := scene.get(key)) is not None and not self._is_removed(elem)
        ]

    def scenes(self) -> tuple[SceneId, ...]:
        """Return every root-bearing scene key, live or since-emptied."""
        return tuple(self._roots_by_scene)

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Remove an indexed element. No-op if absent.

        Index-side cleanup only — the Observer cascade unwinds parent
        composites. Clears the storage so future ``lookup`` calls fail loud,
        and drops a root from the root set so ``scene_roots`` forgets it.
        """
        if not self.contains(scene_id, element_id):
            return
        del self._by_scene[scene_id][element_id]
        self._roots_by_scene.get(scene_id, {}).pop(element_id, None)

    @staticmethod
    def _is_removed(elem: WireElement) -> bool:
        """Return True if ``elem`` is a migrated ABC element flagged removed.

        Legacy wire dataclasses have no lifecycle flag; the ABC type is imported
        lazily to avoid a circular import with ``element_abc``.
        """
        from punt_lux.domain.element_abc import Element as ElementABC

        return isinstance(elem, ElementABC) and elem.removed
