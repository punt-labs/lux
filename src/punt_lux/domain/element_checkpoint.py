"""ElementCheckpoint -- an element's state as it was, to be put back as it was."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.observer_state import ObserversCheckpoint

__all__ = ["ElementCheckpoint"]


@final
class ElementCheckpoint:
    """The state of one element at one moment: its fields, shallowly copied, and the
    state its observers derive from it.

    Setters replace a field, never mutate one in place, so a shallow copy is the whole
    field state. An observer that keeps state of its own (a filtered table's unfiltered
    rows) is checkpointed with the element, so a restore leaves nothing the transaction
    touched as it was not. Putting it back says nothing to the observers that keep no
    state: the transaction that restores tells them, once every element is whole again.
    """

    _element: Element
    _fields: dict[str, object]
    _observers: ObserversCheckpoint
    __slots__ = ("_element", "_fields", "_observers")

    def __new__(cls, element: Element) -> Self:
        self = super().__new__(cls)
        self._element = element
        self._fields = dict(vars(element))
        self._observers = element.observer_checkpoint()
        return self

    @property
    def element(self) -> Element:
        """The element this checkpoint belongs to."""
        return self._element

    def restore(self) -> None:
        """Put the fields, and the state its observers keep, back as they were."""
        fields = vars(self._element)
        fields.clear()
        fields.update(self._fields)
        self._observers.restore()
