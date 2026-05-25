"""ChildIndex — ``(scene_id, parent_id) → tuple[ElementId, ...]`` mapping.

Records the parent → children edges captured when ``HubDisplay.apply``
installs a child Element. The cascade-removal path uses it to enumerate
descendants of a subtree root so the index, owner, and root storage all
drop together — without it, removing a root would orphan its children
in the storage layer even though the property-observer cascade has
already torn down the live composite.

A child Element with no recorded parent is treated as a scene root.
"""

from __future__ import annotations

import contextlib
from typing import Self

from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["ChildIndex"]


class ChildIndex:
    """``(scene_id, parent_id) → tuple[ElementId, ...]`` mapping.

    Maintains both directions: parent → ordered children list (for
    subtree walks) and child → parent (for "is root" queries). The
    parent → child list preserves insertion order so cascade removal
    visits children in the order they were installed.
    """

    _children: dict[tuple[SceneId, ElementId], list[ElementId]]
    _parent: dict[tuple[SceneId, ElementId], ElementId]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._children = {}
        self._parent = {}
        return self

    def record(
        self,
        scene_id: SceneId,
        parent_id: ElementId,
        child_id: ElementId,
    ) -> None:
        """Record ``child_id`` as a child of ``parent_id`` in ``scene_id``."""
        self._children.setdefault((scene_id, parent_id), []).append(child_id)
        self._parent[(scene_id, child_id)] = parent_id

    def is_root(self, scene_id: SceneId, element_id: ElementId) -> bool:
        """Return True if ``element_id`` has no recorded parent in ``scene_id``."""
        return (scene_id, element_id) not in self._parent

    def descendants(
        self, scene_id: SceneId, element_id: ElementId
    ) -> tuple[ElementId, ...]:
        """Return ``element_id``'s descendants in install order.

        Walks the parent → child edges depth-first. The element itself
        is not included; callers that want it must concatenate.
        """
        result: list[ElementId] = []
        stack: list[ElementId] = [element_id]
        while stack:
            current = stack.pop()
            if current != element_id:
                result.append(current)
            children = self._children.get((scene_id, current), ())
            # Push in reverse so the first-installed child is popped first,
            # yielding install-order DFS.
            stack.extend(reversed(children))
        return tuple(result)

    def discard(self, scene_id: SceneId, element_id: ElementId) -> None:
        """Drop every edge referencing ``element_id``. No-op if absent.

        Removes ``element_id`` from its parent's children list, drops
        its own children list, and clears its child → parent entry.
        Does not recurse — callers walk ``descendants`` first and call
        ``discard`` on each in turn.
        """
        parent = self._parent.pop((scene_id, element_id), None)
        if parent is not None:
            siblings = self._children.get((scene_id, parent))
            if siblings is not None:
                with contextlib.suppress(ValueError):
                    siblings.remove(element_id)
                if not siblings:
                    del self._children[(scene_id, parent)]
        self._children.pop((scene_id, element_id), None)
