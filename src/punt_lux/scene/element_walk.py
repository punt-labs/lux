"""Scene element-tree traversal — locate, collect ids, detach.

Splits the recursive tree helpers out of :class:`SceneManager` so the
state machine owns scene lifecycle and this module owns tree navigation.

Removal is physical in BOTH element models: a legacy element is popped
from its parent list, an ABC element is dropped from its parent's child
tuple. The Display renders whatever ``_children()`` returns, so a detached
element stops painting at once — the Hub store and the Display replica
agree that "detached" means "gone", never "flagged but still rendered".

``ListSlot`` (a legacy list + index) and ``AbcNode`` (an ABC element + its
parent container) are the two location kinds; each owns how to apply a
set-patch and how to detach, so the caller never branches on the model.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self, cast, final

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.protocol import (
    CollapsingHeaderElement,
    Element,
    LegacyGroupElement,
    ModalElement,
    TabBarElement,
    WindowElement,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["AbcNode", "ElementLocation", "ListSlot", "SceneTreeWalk"]


@final
class ListSlot:
    """A located element at a mutable index in a legacy container's list.

    A set-patch rebinds the slot (a frozen legacy dataclass is replaced; an
    ABC leaf nested in a legacy list mutates in place and the slot rebinds
    to the same object). A remove pops the element out of its parent list.
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
        """Apply ``fields`` to the slotted element; return the result."""
        elem = self._parent[self._index]
        if isinstance(elem, ABCElement):
            elem.apply_patch(fields)
            return elem
        updated = replace(elem, **fields)
        self._parent[self._index] = updated
        return updated

    def detach(self) -> Element:
        """Pop the element out of its parent list and return it."""
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

    Stateless: one instance is as good as any other. Legacy containers are
    descended through their mutable backing lists (so a found legacy element
    can be rebound or popped); ABC containers through ``HasChildElements``.
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

        A direct member is a :class:`ListSlot` (``elements`` is a mutable
        list). A match deeper in an ABC container is an :class:`AbcNode`;
        deeper in a legacy container, a :class:`ListSlot` over that
        container's backing list.
        """
        for index, element in enumerate(elements):
            if getattr(element, "id", None) == target_id:
                return ListSlot(elements, index)
            found = self._descend(element, target_id)
            if found is not None:
                return found
        return None

    def _descend(self, element: object, target_id: str) -> ElementLocation | None:
        """Search ``element``'s children for ``target_id`` in either model."""
        if isinstance(element, ABCElement):
            return self._find_in_abc(element, target_id)
        for child_list in self._legacy_child_lists(element):
            found = self.find(child_list, target_id)
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

    def _legacy_child_lists(self, element: object) -> list[list[Element]]:
        """Return the mutable backing child lists of a legacy container.

        Legacy mutation needs the actual list to pop or rebind an entry.
        Every legacy ``HasChildElements`` kind must appear here — an omission
        makes ``find`` unable to reach a child ``collect_ids`` reports.
        """
        if isinstance(element, LegacyGroupElement):
            lists: list[list[Element]] = [element.children]
            lists.extend(element.pages)
            return lists
        if isinstance(element, (CollapsingHeaderElement, WindowElement, ModalElement)):
            return [element.children]
        if isinstance(element, TabBarElement):
            return [tab.get("children", []) for tab in element.tabs]
        return []
