"""ElementCheckpoint -- an element's field state as it was, to be put back as it was."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element

__all__ = ["ElementCheckpoint"]


@final
class ElementCheckpoint:
    """The field state of one element at one moment, shallowly copied.

    Setters replace a field, never mutate one in place, so a shallow copy is the whole
    state. Putting it back says nothing to the element's observers: the transaction
    that restores tells them, once every element is whole again.
    """

    _element: Element
    _fields: dict[str, object]
    __slots__ = ("_element", "_fields")

    def __new__(cls, element: Element) -> Self:
        self = super().__new__(cls)
        self._element = element
        self._fields = dict(vars(element))
        return self

    @property
    def element(self) -> Element:
        """The element this checkpoint belongs to."""
        return self._element

    def restore(self) -> None:
        """Put the element's field state back exactly as it was."""
        fields = vars(self._element)
        fields.clear()
        fields.update(self._fields)
