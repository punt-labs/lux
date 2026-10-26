"""ObserverState -- state an observer derives from an element, kept so it can be undone.

An observer that keeps state of its own (a filtered table's unfiltered rows, its filter
and its full selection) cannot be undone by putting the element back: told the restored
value it would take it for a new write. Such an observer is registered as a
:class:`StatefulObserver`, which carries both the callback it is told changes by and
the checkpoint of its state; the restore puts that state back instead of telling it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["ObserverCheckpoint", "ObserversCheckpoint", "StatefulObserver"]


class ObserverCheckpoint(Protocol):
    """One observer's state at one moment, able to put it back."""

    def restore(self) -> None:
        """Put the observer's state back exactly as it was."""
        ...


class StatefulObserver(Protocol):
    """An observer whose own state a transaction must be able to undo."""

    def on_change(self, prop: str) -> None:
        """Be told that the element's property ``prop`` changed."""
        ...

    def checkpoint(self) -> ObserverCheckpoint:
        """Return the observer's state now, to be restored on a rollback."""
        ...


@final
class ObserversCheckpoint:
    """The checkpoints of every stateful observer of one element, in order."""

    _parts: tuple[ObserverCheckpoint, ...]
    __slots__ = ("_parts",)

    def __new__(cls, parts: Iterable[ObserverCheckpoint]) -> Self:
        self = super().__new__(cls)
        self._parts = tuple(parts)
        return self

    def restore(self) -> None:
        """Put every observer's state back, in the order it was taken."""
        for part in self._parts:
            part.restore()
