"""Scene element-tree traversal — locate, collect ids, mutate in place.

Splits the recursive tree helpers out of :class:`SceneManager` so the
state machine owns scene lifecycle and this module owns tree navigation.

The walk descends both element models uniformly. Legacy dataclass
containers expose mutable backing child lists, so a located legacy
element carries the list + index needed to rebind or pop it. ABC
containers expose an immutable child *tuple* through the
:class:`HasChildElements` Protocol — the same contract the validation and
inspection walks use — and their elements mutate IN PLACE (``apply_patch``
for a set-patch, ``mark_removed`` for a remove), so the tuple is never
rebound.

``ListSlot`` and ``AbcNode`` are the two location kinds; each owns how to
apply a set-patch and how to detach its element, so the caller never
branches on which model it found.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.protocol import (
    CollapsingHeaderElement,
    Element,
    LegacyGroupElement,
    TabBarElement,
    WindowElement,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["AbcNode", "ElementLocation", "ListSlot", "SceneTreeWalk"]


class ListSlot:
    """A located element at a mutable index in a legacy container's list.

    A set-patch rebinds the slot (a legacy dataclass is frozen, so it is
    replaced by a new instance; an ABC leaf nested in a legacy list
    mutates in place and the slot is rebound to the same object). A remove
    pops the element out of its parent list.
    """

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
        """Apply ``fields`` to the slotted element; return the result.

        An ABC leaf patches in place; a frozen legacy dataclass is
        replaced and the slot rebound to the new instance.
        """
        elem = self._parent[self._index]
        if isinstance(elem, ABCElement):
            elem.apply_patch(fields)
            return elem
        updated = replace(elem, **fields)
        self._parent[self._index] = updated
        return updated

    def detach(self) -> Element:
        """Remove the element from its parent list and return it."""
        return self._parent.pop(self._index)


class AbcNode:
    """A located ABC element inside an immutable container tuple.

    ABC elements mutate in place: a set-patch runs ``apply_patch`` on the
    element, a remove runs ``mark_removed``. The parent tuple is never
    rebound — the located object IS the authoritative one the container
    holds, so mutating it is visible to the render.
    """

    _element: Element

    def __new__(cls, element: Element) -> Self:
        self = super().__new__(cls)
        self._element = element
        return self

    @property
    def element(self) -> Element:
        """Return the located ABC element."""
        return self._element

    def apply_set(self, fields: Mapping[str, Any]) -> Element:
        """Patch the element in place and return it."""
        elem = self._element
        if isinstance(elem, ABCElement):
            elem.apply_patch(fields)
        return elem

    def detach(self) -> Element:
        """Mark the element removed and return it (the tuple is untouched)."""
        elem = self._element
        if isinstance(elem, ABCElement):
            elem.mark_removed()
        return elem


type ElementLocation = ListSlot | AbcNode


class SceneTreeWalk:
    """Navigate a scene's element tree — find, collect ids, locate for patch.

    Stateless: one instance is as good as any other. Legacy containers are
    descended through their mutable backing lists (so a found legacy
    element can be rebound or popped); ABC containers are descended through
    the ``HasChildElements`` Protocol.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def collect_ids(self, element: object) -> list[str]:
        """Collect every element id in a subtree, including the root.

        Recurses containers of both models uniformly via
        ``HasChildElements`` — so an ABC group's nested children are
        reported, not skipped.
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

        A direct member is returned as a :class:`ListSlot` (``elements`` is
        a mutable list). A match deeper in an ABC container is an
        :class:`AbcNode`; deeper in a legacy container, a :class:`ListSlot`
        over that container's backing list.
        """
        for index, element in enumerate(elements):
            if getattr(element, "id", None) == target_id:
                return ListSlot(elements, index)
            found = self._descend(element, target_id)
            if found is not None:
                return found
        return None

    def _descend(self, element: object, target_id: str) -> ElementLocation | None:
        """Search ``element``'s children for ``target_id``."""
        if isinstance(element, ABCElement):
            return self._find_in_abc(element, target_id)
        for child_list in self._legacy_child_lists(element):
            found = self.find(child_list, target_id)
            if found is not None:
                return found
        return None

    def _find_in_abc(self, element: ABCElement, target_id: str) -> AbcNode | None:
        """Search an ABC container's tuple children for ``target_id``.

        ``child_elements()`` yields ABC elements; a leaf's is empty, so
        recursing into every child descends containers and no-ops on
        leaves without a separate container check.
        """
        for child in element.child_elements():
            if child.id == target_id:
                return AbcNode(cast("Element", child))
            found = self._find_in_abc(child, target_id)
            if found is not None:
                return found
        return None

    def _legacy_child_lists(self, element: object) -> list[list[Element]]:
        """Return the mutable backing child lists of a legacy container.

        Legacy mutation needs the actual list to pop or rebind an entry;
        ``child_elements()`` yields a computed tuple, so the ladder reads
        each legacy container's own list-shaped children directly.
        """
        if isinstance(element, LegacyGroupElement):
            lists: list[list[Element]] = [element.children]
            lists.extend(element.pages)
            return lists
        if isinstance(element, (CollapsingHeaderElement, WindowElement)):
            return [element.children]
        if isinstance(element, TabBarElement):
            return [tab.get("children", []) for tab in element.tabs]
        return []
