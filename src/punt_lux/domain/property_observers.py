"""PropertyObservers -- who is told when an element's property changes.

An element's observers are told which property changed. A raising observer is logged
and skipped: one bad subscriber must not strand the others (PY-EH-6 system-boundary
exemption). A :class:`~punt_lux.domain.programmer_error.ProgrammerError` is no
subscriber's own failure and goes through.

A write an observer made that the judge refused is no bug of the observer's. It runs
its course through the other observers and is raised after them, so the transaction
that woke the observer can roll back.

An observer that keeps state of its own registers with ``add_stateful``. A rollback
restores that state from a checkpoint and does not tell the observer the restored
values, which it would take for a new write; the observers that keep none are told.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.handler_writes import WriteRefusedError
from punt_lux.domain.observer_entries import KeepingObserver, PlainObserver
from punt_lux.domain.observer_state import ObserversCheckpoint
from punt_lux.domain.programmer_error import ProgrammerError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from punt_lux.domain.observer_entries import ObserverEntry
    from punt_lux.domain.observer_state import StatefulObserver

logger = logging.getLogger(__name__)

__all__ = ["PropertyObservers"]


@final
class PropertyObservers:
    """The observers of one element, in the order they registered."""

    _observers: list[ObserverEntry]
    __slots__ = ("_observers",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._observers = []
        return self

    def add(self, observer: Callable[[str], None]) -> None:
        """Register an observer that keeps no state: it is told ``prop`` changed."""
        self._observers.append(PlainObserver(observer))

    def add_stateful(self, observer: StatefulObserver) -> None:
        """Register an observer whose own state a rollback must restore."""
        self._observers.append(KeepingObserver(observer))

    def checkpoint(self) -> ObserversCheckpoint:
        """Return the state of every observer that keeps any, to restore on undo."""
        return ObserversCheckpoint(
            part for observer in self._observers for part in observer.kept_state()
        )

    def announce(
        self, props: Iterable[str], element_id: str, *, restored: bool = False
    ) -> None:
        """Tell the observers that each of ``props`` changed, each prop once.

        With ``restored`` a rollback has put each prop back: the observers that keep
        state hear nothing, since theirs came back from their checkpoint. A refused
        write an observer made does not stop the props after it from being heard: the
        first refusal is raised once every prop has been announced.
        """
        snapshot = tuple(self._observers)  # a snapshot: an observer may register one
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for prop in dict.fromkeys(props):
            try:
                self._tell(snapshot, prop, element_id, restored=restored)
            except WriteRefusedError as exc:
                refused = refused or exc
        if refused is not None:
            raise refused

    @staticmethod
    def _tell(
        observers: Iterable[ObserverEntry],
        prop: str,
        element_id: str,
        *,
        restored: bool,
    ) -> None:
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for observer in observers:
            try:
                if restored:
                    observer.on_restored(prop)
                else:
                    observer.on_change(prop)
            except WriteRefusedError as exc:
                refused = refused or exc
            except ProgrammerError:
                raise
            except Exception:
                logger.exception(
                    "observer %r failed on %r of element %s", observer, prop, element_id
                )
        if refused is not None:
            raise refused
