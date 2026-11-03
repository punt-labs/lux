"""ObserverEntries -- the two kinds of observer an element holds, told apart by type.

An element's observers are told in the order they registered. Most are plain callbacks
and keep nothing: after a rollback they are told what was restored. One that derives
state of its own is a stateful observer: its state is restored from a checkpoint and it
is told nothing. Each entry answers the same three messages, so no caller asks which
kind it holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.observer_state import ObserverCheckpoint, StatefulObserver

__all__ = ["KeepingObserver", "ObserverEntry", "PlainObserver"]


class ObserverEntry(Protocol):
    """One registered observer, as an element's observers hold it."""

    def on_change(self, prop: str) -> None:
        """Tell the observer that ``prop`` changed."""
        ...

    def on_restored(self, prop: str) -> None:
        """Tell the observer that a rollback put ``prop`` back, if it wants telling."""
        ...

    def kept_state(self) -> tuple[ObserverCheckpoint, ...]:
        """Return the checkpoints of the state it keeps; none if it keeps none."""
        ...


@final
class PlainObserver:
    """A callback that keeps no state: a rollback tells it what was restored."""

    _callback: Callable[[str], None]
    __slots__ = ("_callback",)

    def __new__(cls, callback: Callable[[str], None]) -> Self:
        self = super().__new__(cls)
        self._callback = callback
        return self

    def __repr__(self) -> str:
        return f"PlainObserver({self._callback!r})"

    def on_change(self, prop: str) -> None:
        """Tell the callback that ``prop`` changed."""
        self._callback(prop)

    def on_restored(self, prop: str) -> None:
        """Tell the callback ``prop`` was put back: it has nothing else to restore."""
        self._callback(prop)

    def kept_state(self) -> tuple[ObserverCheckpoint, ...]:
        """Return no checkpoints: a plain callback keeps no state."""
        return ()


@final
class KeepingObserver:
    """An observer with state of its own: a rollback restores it, tells it nothing."""

    _observer: StatefulObserver
    __slots__ = ("_observer",)

    def __new__(cls, observer: StatefulObserver) -> Self:
        self = super().__new__(cls)
        self._observer = observer
        return self

    def __repr__(self) -> str:
        return f"KeepingObserver({self._observer!r})"

    def on_change(self, prop: str) -> None:
        """Tell the observer that ``prop`` changed."""
        self._observer.on_change(prop)

    def on_restored(self, prop: str) -> None:
        """Say nothing: its state comes back from its checkpoint, not from a write."""

    def kept_state(self) -> tuple[ObserverCheckpoint, ...]:
        """Return the checkpoint of the observer's own state."""
        return (self._observer.checkpoint(),)
