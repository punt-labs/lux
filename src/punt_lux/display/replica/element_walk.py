"""Scene element-tree traversal — locate, collect ids, detach.

Splits the recursive tree helpers out of :class:`SceneReplica` so the
state machine owns scene lifecycle and this module owns tree navigation.

Removal is physical: a scene-root element is popped from the scene's root
list, a nested element is dropped from its parent's child tuple. The Display
renders whatever ``_children()`` returns, so a detached element stops painting
at once — the Hub store and the Display replica agree that "detached" means
"gone", never "flagged but still rendered".

``ListSlot`` (the scene-root list + index) and ``AbcNode`` (an element + its
parent container) are the two location kinds; each owns how to apply a
set-patch and how to detach, so the caller never branches on where it sits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, cast, final

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.protocol import Element

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["AbcNode", "ElementLocation", "ListSlot", "SceneTreeWalk"]


@final
class ListSlot:
    """A located element at a mutable index in the scene's root list.

    A set-patch mutates the element in place (``apply_patch``); a remove pops
    it out of the root list.
    """

    __slots__ = ("_index", "_parent")

    _parent: list[Element]
    _index: int

    def __new__(cls, parent: list[Element], index: int) -> Self:
        self = super().__new__(cls)
        self._parent = parent
        self._index = index
        return self

    @property
    def element(self) -> Element:
        """Return the element currently occupying this slot."""
        return self._parent[self._index]

    def apply_set(self, fields: Mapping[str, Any]) -> Element:
        """Apply ``fields`` to the slotted element in place; return the result."""
        elem = self._parent[self._index]
        elem.apply_patch(fields)
        return elem

    def detach(self) -> Element:
        """Pop the element out of the scene's root list and return it."""
        return self._parent.pop(self._index)


@final
class AbcNode:
    """A located ABC element together with its parent ABC container.

    A set-patch runs ``apply_patch`` on the element in place. A remove calls
    ``remove_child`` on the parent, which rebinds the parent's child tuple
    to exclude this element — physical removal, so the render walk over
    ``_children()`` no longer paints it.
    """

    __slots__ = ("_element", "_parent")

    _parent: ABCElement
    _element: ABCElement

    def __new__(cls, parent: ABCElement, element: ABCElement) -> Self:
        self = super().__new__(cls)
        self._parent = parent
        self._element = element
        return self

    def __repr__(self) -> str:
        """Return a debug repr naming the located element and its parent."""
        return f"AbcNode(parent={self._parent.id!r}, element={self._element.id!r})"

    @property
    def element(self) -> Element:
        """Return the located ABC element as a wire element."""
        return cast("Element", self._element)

    def apply_set(self, fields: Mapping[str, Any]) -> Element:
        """Patch the element in place and return it."""
        self._element.apply_patch(fields)
        return self.element

    def detach(self) -> Element:
        """Drop the element from its parent's children and return it."""
        self._parent.remove_child(self._element)
        return self.element


type ElementLocation = ListSlot | AbcNode


@final
class SceneTreeWalk:
    """Navigate a scene's element tree — find, collect ids, locate for patch.

    Stateless: one instance is as good as any other. Containers are descended
    through ``HasChildElements``; a scene-root match is a :class:`ListSlot`, a
    nested match an :class:`AbcNode`.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def collect_ids(self, element: object) -> list[str]:
        """Collect every element id in a subtree, including the root.

        Recurses containers uniformly via ``HasChildElements`` — so an ABC
        group's nested children are reported, not skipped.
        """
        ids: list[str] = []
        eid = getattr(element, "id", None)
        if isinstance(eid, str):
            ids.append(eid)
        if isinstance(element, HasChildElements):
            for child in element.child_elements():
                ids.extend(self.collect_ids(child))
        return ids

    def find(self, elements: list[Element], target_id: str) -> ElementLocation | None:
        """Locate ``target_id`` within ``elements``, or return ``None``.

        A direct member is a :class:`ListSlot` (``elements`` is the scene's
        mutable root list). A match deeper in a container is an :class:`AbcNode`.
        """
        for index, element in enumerate(elements):
            if getattr(element, "id", None) == target_id:
                return ListSlot(elements, index)
            found = self._find_in_abc(element, target_id)
            if found is not None:
                return found
        return None

    def _find_in_abc(self, element: ABCElement, target_id: str) -> AbcNode | None:
        """Search an ABC container's children for ``target_id``.

        ``child_elements()`` yields ABC elements; a leaf's is empty, so
        recursing into every child descends containers and no-ops on leaves.
        A direct match carries ``element`` as its parent so a remove can
        rebind that child tuple.
        """
        for child in element.child_elements():
            if child.id == target_id:
                return AbcNode(element, child)
            found = self._find_in_abc(child, target_id)
            if found is not None:
                return found
        return None
