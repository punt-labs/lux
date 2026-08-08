"""DismissalWalk — the closest self-or-ancestor whose ``removed`` flag is set.

Only a scene-root Element's ``mark_removed`` routes back through
``HubDisplay.apply`` and drops its subtree from the index
(``SubtreeInstaller`` registers that observer on roots only). A non-root
ancestor marked removed by its own parent composite stays indexed, so a
click on a surviving descendant would otherwise still resolve and fire.
This class is the one place that walk lives, over the two collaborators
that carry the data it needs: ``ElementIndex`` for the removed flag,
``ChildIndex`` for the parent edge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError

if TYPE_CHECKING:
    from punt_lux.domain.hub.child_index import ChildIndex
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["DismissalWalk"]


@final
class DismissalWalk:
    """Walk self-and-ancestors over an ``ElementIndex`` and a ``ChildIndex``."""

    _index: ElementIndex
    _children: ChildIndex
    __slots__ = ("_children", "_index")

    def __new__(cls, index: ElementIndex, children: ChildIndex) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._children = children
        return self

    def nearest_dismissed(
        self, scene_id: SceneId, element_id: ElementId
    ) -> ElementId | None:
        """Return the closest self-or-ancestor whose ``removed`` flag is set.

        Only ABC Elements carry ``removed``; a wire dataclass ancestor is
        never marked individually and is skipped. The walk includes
        ``element_id`` itself and stops at a root or an element unknown to
        the index.
        """
        current_id: ElementId | None = element_id
        while current_id is not None:
            try:
                elem = self._index.lookup(scene_id, current_id)
            except (UnknownElementError, UnknownSceneError):
                return None
            if isinstance(elem, AbcElement) and elem.removed:
                return current_id
            current_id = self._children.parent_of(scene_id, current_id)
        return None
