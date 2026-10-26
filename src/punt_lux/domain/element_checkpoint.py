"""ElementCheckpoint -- an element's state as it was, to be put back as it was."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.observer_state import ObserversCheckpoint

__all__ = ["ElementCheckpoint"]


@final
class ElementCheckpoint:
    """The state of one element at one moment: its fields, shallowly copied, the state
    of the parts it owns, and the state its observers derive from it.

    Setters replace a field, never mutate one in place, so a shallow copy is the whole
    field state of the element. A part it owns (a dialog's model) mutates in place, so
    its fields are copied the same way. An observer that keeps state of its own (a
    filtered table's unfiltered rows) is checkpointed with the element, so a restore
    leaves nothing the transaction touched as it was not. Putting it back says nothing
    to the observers that keep no state: the transaction that restores tells them, once
    every element is whole again.
    """

    _element: Element
    _fields: dict[str, object]
    _parts: tuple[tuple[object, dict[str, object]], ...]
    _observers: ObserversCheckpoint
    __slots__ = ("_element", "_fields", "_observers", "_parts")

    def __new__(cls, element: Element) -> Self:
        self = super().__new__(cls)
        self._element = element
        self._fields = dict(vars(element))
        owned: list[object] = [getattr(element, name) for name in element.OWNED_PARTS]
        self._parts = tuple((part, dict(vars(part))) for part in owned)
        self._observers = element.observer_checkpoint()
        return self

    @property
    def element(self) -> Element:
        """The element this checkpoint belongs to."""
        return self._element

    def restore(self) -> None:
        """Put the fields, the parts' fields and the observers' state back."""
        self._put_back(self._element, self._fields)
        for part, fields in self._parts:
            self._put_back(part, fields)
        self._observers.restore()

    @staticmethod
    def _put_back(target: object, fields: dict[str, object]) -> None:
        current = vars(target)
        current.clear()
        current.update(fields)
