"""BatchJudge -- the judge in force while a batch of agent writes is committed.

A batch is judged whole before its first commit, so each write the batch itself makes
is already judged and is let through here, once: the write is the element and the very
patch mapping the batch holds for it, by identity. Every other write, such as one an
observer of an earlier target makes to a later target, goes to the seam's own judge
like any other.

The judge also sees every write the batch causes, observers' writes included, before
the element is touched, so it is where the batch's undo lives: the first state of
each element written, and the properties written. A batch that fails puts every one
of them back and tells the observers of each what it holds again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_checkpoint import ElementCheckpoint
from punt_lux.domain.handler_writes import WriteRefusedError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.handler_writes import WriteJudge

logger = logging.getLogger(__name__)

__all__ = ["BatchJudge"]


@final
@dataclass(frozen=True, slots=True)
class _Written:
    """One element the batch wrote: how it was first, and which properties changed."""

    first: ElementCheckpoint
    # An insertion-ordered set: the order the properties are announced in is the order
    # they were first written, never a hash order.
    props: dict[str, None] = field(default_factory=lambda: dict[str, None]())


@final
class BatchJudge:
    """Lets each pre-judged write of the batch through once, and judges the rest."""

    _admit: WriteJudge
    _unspent: list[tuple[Element, Mapping[str, object]]]
    _written: dict[int, _Written]
    _is_rolling_back: bool
    __slots__ = ("_admit", "_is_rolling_back", "_unspent", "_written")

    def __new__(
        cls,
        admit: WriteJudge,
        writes: Iterable[tuple[Element, Mapping[str, object]]],
    ) -> Self:
        self = super().__new__(cls)
        self._admit = admit
        self._unspent = list(writes)
        self._written = {}
        self._is_rolling_back = False
        return self

    @property
    def written(self) -> tuple[Element, ...]:
        """Every element the batch has written so far, in the order it first did."""
        return tuple(w.first.element for w in self._written.values())

    def __call__(self, element: Element, patch: Mapping[str, object]) -> None:
        if not patch:  # nothing to judge: an observer saying it is about to derive
            self._record(element, patch)  # state, so the batch checkpoints it first
            return
        for index, (target, fields) in enumerate(self._unspent):
            if target is element and fields is patch:
                del self._unspent[index]
                self._record(element, patch)
                return
        self._admit(element, patch)
        self._record(element, patch)  # only a write the judge admitted is recorded

    def roll_back(self) -> None:
        """Put every element the batch wrote back as it first was, then say so.

        All the state is restored before any observer is told, so each hears a scene
        that is whole again. A write an observer then makes is judged like any other;
        one it refuses is logged, since the batch is failing already. A second call
        raises ``RuntimeError``: a judge serves one batch.
        """
        if self._is_rolling_back:
            msg = "a batch judge rolls back once: the elements are restored already"
            raise RuntimeError(msg)
        self._is_rolling_back = True
        written = list(self._written.values())
        for entry in reversed(written):
            entry.first.restore()
        for entry in written:
            try:
                entry.first.element.announce_restored(entry.props)
            except WriteRefusedError:
                logger.warning(
                    "an observer's write was refused while rolling back %s",
                    entry.first.element.id,
                )

    def _record(self, element: Element, patch: Mapping[str, object]) -> None:
        if self._is_rolling_back:
            return
        entry = self._written.get(id(element))
        if entry is None:
            entry = self._written[id(element)] = _Written(ElementCheckpoint(element))
        entry.props.update(dict.fromkeys(patch))
