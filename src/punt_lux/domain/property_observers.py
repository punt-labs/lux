"""PropertyObservers -- who is told when an element's property changes, and when.

An element's observers are told which property changed. Inside a patch the telling is
*buffered* and happens only when the patch commits, so a patch that fails midway tells
nobody; outside a patch it happens at once. A raising observer is logged and skipped:
one bad subscriber must not strand the others (PY-EH-6 system-boundary exemption).

A write an observer made that the judge refused is no bug of the observer's. It runs
its course through the other observers and is raised after them, so the transaction
that woke the observer can roll back.

An observer that keeps state of its own registers it too. A rollback restores that
state from a checkpoint and does not tell the observer the restored values, which it
would take for a new write; the observers that keep none are told.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.handler_writes import WriteRefusedError
from punt_lux.domain.observer_state import ObserversCheckpoint

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from punt_lux.domain.observer_state import StatefulObserver

logger = logging.getLogger(__name__)

__all__ = ["PropertyObservers"]


@final
class PropertyObservers:
    """The observers of one element, and the buffer a patch in progress fills."""

    _callbacks: list[Callable[[str], None]]
    # The observers that keep state of their own, each with the callback it listens by.
    _stateful: list[tuple[Callable[[str], None], StatefulObserver]]
    # PY-TS-14 OK: ``None`` means "not inside a patch, notify immediately"; a list is
    # the per-patch buffer that defers notifications until commit.
    _buffer: list[str] | None
    __slots__ = ("_buffer", "_callbacks", "_stateful")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._callbacks = []
        self._stateful = []
        self._buffer = None
        return self

    def add(
        self,
        observer: Callable[[str], None],
        state: StatefulObserver | None = None,  # PY-TS-14 OK: most keep no state
    ) -> None:
        """Register an observer of property changes, and the state it keeps if any."""
        self._callbacks.append(observer)
        if state is not None:
            self._stateful.append((observer, state))

    def checkpoint(self) -> ObserversCheckpoint:
        """Return the state of every observer that keeps any, to restore on undo."""
        return ObserversCheckpoint(state for _, state in self._stateful)

    def begin(self) -> None:
        """Start buffering: the patch in progress tells nobody until it commits."""
        self._buffer = []

    def discard(self) -> None:
        """Drop what the patch buffered: it failed, and tells nobody."""
        self._buffer = None

    def commit(self, element_id: str) -> None:
        """Tell the observers of every property the patch changed, each once."""
        pending = self._buffer or []
        self._buffer = None
        self.announce(pending, element_id)

    def notify(self, prop: str, element_id: str) -> None:
        """Tell the observers that ``prop`` changed, or buffer it inside a patch."""
        if self._buffer is not None:
            self._buffer.append(prop)
            return
        self._tell(tuple(self._callbacks), prop, element_id)  # a snapshot: may add

    def announce(self, props: Iterable[str], element_id: str) -> None:
        """Tell the observers that each of ``props`` changed, each prop once.

        A refused write an observer made does not stop the props after it from being
        heard: the first refusal is raised once every prop has been announced.
        """
        self._announce(props, element_id, self.notify)

    def announce_restored(self, props: Iterable[str], element_id: str) -> None:
        """Tell the observers that keep no state that each of ``props`` is restored.

        The ones that keep state were restored from their checkpoint and hear nothing.
        """
        keeping = {id(callback) for callback, _ in self._stateful}
        told = tuple(c for c in self._callbacks if id(c) not in keeping)
        self._announce(props, element_id, lambda prop, eid: self._tell(told, prop, eid))

    @staticmethod
    def _announce(
        props: Iterable[str],
        element_id: str,
        tell: Callable[[str, str], None],
    ) -> None:
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for prop in dict.fromkeys(props):
            try:
                tell(prop, element_id)
            except WriteRefusedError as exc:
                refused = refused or exc
        if refused is not None:
            raise refused

    @staticmethod
    def _tell(
        observers: Iterable[Callable[[str], None]], prop: str, element_id: str
    ) -> None:
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for observer in observers:
            try:
                observer(prop)
            except WriteRefusedError as exc:
                refused = refused or exc
            except Exception:
                logger.exception(
                    "observer %r failed on %r of element %s", observer, prop, element_id
                )
        if refused is not None:
            raise refused
