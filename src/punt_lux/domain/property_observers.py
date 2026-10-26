"""PropertyObservers -- who is told when an element's property changes, and when.

An element's observers are told which property changed. Inside a patch the telling is
*buffered* and happens only when the patch commits, so a patch that fails midway tells
nobody; outside a patch it happens at once. A raising observer is logged and skipped:
one bad subscriber must not strand the others (PY-EH-6 system-boundary exemption).

A write an observer made that the judge refused is no bug of the observer's. It runs
its course through the other observers and is raised after them, so the transaction
that woke the observer can roll back.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.handler_writes import WriteRefusedError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

__all__ = ["PropertyObservers"]


@final
class PropertyObservers:
    """The observers of one element, and the buffer a patch in progress fills."""

    _callbacks: list[Callable[[str], None]]
    # PY-TS-14 OK: ``None`` means "not inside a patch, notify immediately"; a list is
    # the per-patch buffer that defers notifications until commit.
    _buffer: list[str] | None
    __slots__ = ("_buffer", "_callbacks")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._callbacks = []
        self._buffer = None
        return self

    def add(self, observer: Callable[[str], None]) -> None:
        """Register an observer of property changes."""
        self._callbacks.append(observer)

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
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for observer in tuple(self._callbacks):  # a snapshot: a callback may add
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

    def announce(self, props: Iterable[str], element_id: str) -> None:
        """Tell the observers that each of ``props`` changed, each prop once.

        A refused write an observer made does not stop the props after it from being
        heard: the first refusal is raised once every prop has been announced.
        """
        refused: WriteRefusedError | None = None  # PY-TS-14 OK: None, nothing refused
        for prop in dict.fromkeys(props):
            try:
                self.notify(prop, element_id)
            except WriteRefusedError as exc:
                refused = refused or exc
        if refused is not None:
            raise refused
