"""BatchJudge -- the transaction in force while a batch of writes is committed.

A batch is judged whole before its first commit, so each write the batch itself makes
is already judged and is let through here, once: the write is the element and the very
patch mapping the batch holds for it, by identity. Every other write, such as one an
observer of an earlier target makes to a later target, goes to the seam's own judge
like any other.

The judge also sees every write the batch causes, observers' writes included, before
the element is touched, so it is where the batch's undo lives: the first state of
each element written or about to derive state, and the properties written. A batch
that fails puts every one of them back and tells the observers of each what it holds
again. An element removed inside the batch is not removed until the batch stands, so
a batch that fails has no removal to undo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.element_checkpoint import ElementCheckpoint
from punt_lux.domain.hub.transaction_errors import (
    JudgeReusedError,
    WriteDuringRollbackError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.handler_writes import WriteJudge

__all__ = ["BatchJudge"]


@final
@dataclass(frozen=True, slots=True)
class _Written:
    """One element the batch touched: how it was first, and which properties changed."""

    first: ElementCheckpoint
    # An insertion-ordered set: the order the properties are announced in is the order
    # they were first written, never a hash order.
    props: dict[str, None] = field(default_factory=lambda: dict[str, None]())


@final
class BatchJudge:
    """Lets each pre-judged write of the batch through once, and judges the rest."""

    _admit: WriteJudge
    _unspent: list[tuple[Element, Mapping[str, object]]]
    _touched: dict[int, _Written]
    # The elements a write was made to, in the order they first were. An element that
    # is only checkpointed because it is about to derive state is not among them.
    _wrote: dict[int, None]
    _removals: dict[int, Element]
    _phase: Literal["open", "rolling_back", "settled"]
    __slots__ = ("_admit", "_phase", "_removals", "_touched", "_unspent", "_wrote")

    def __new__(
        cls,
        admit: WriteJudge,
        writes: Iterable[tuple[Element, Mapping[str, object]]],
    ) -> Self:
        self = super().__new__(cls)
        self._admit = admit
        self._unspent = list(writes)
        self._touched = {}
        self._wrote = {}
        self._removals = {}
        self._phase = "open"
        return self

    @property
    def written(self) -> tuple[Element, ...]:
        """Every element a write was made to, in the order it first was, that stays.

        An element the batch removes is not among them: it has no scene left to measure.
        """
        return tuple(
            self._touched[key].first.element
            for key in self._wrote
            if key not in self._removals
        )

    def admit(self, element: Element, patch: Mapping[str, object]) -> None:
        """Judge a write to ``element``; raise to refuse it, record it once admitted."""
        self._require_not_rolling_back("a write")
        for index, (target, fields) in enumerate(self._unspent):
            if target is element and fields is patch:
                del self._unspent[index]
                break
        else:
            self._admit(element, patch)
        entry = self._entry_of(element)  # only a write the judge admitted is recorded
        entry.props.update(dict.fromkeys(patch))
        self._wrote[id(element)] = None

    def note_derivation(self, element: Element) -> None:
        """Checkpoint ``element`` before it changes state no patch names; no write."""
        self._require_not_rolling_back("a derivation")
        self._entry_of(element)

    def defer_removal(self, element: Element) -> None:
        """Take custody of ``element``'s removal; it is carried out at ``commit``."""
        self._require_not_rolling_back("a removal")
        self._removals.setdefault(id(element), element)

    def commit(self) -> None:
        """The batch stood: remove the elements it removed, in the order asked."""
        self._settle()
        removals = tuple(self._removals.values())
        self._removals.clear()
        for element in removals:
            element.mark_removed()

    def roll_back(self) -> None:
        """Put every element the batch touched back as it first was, then say so.

        All the state is restored before any observer is told, so each hears a scene
        that is whole again. A write an observer then makes would move state past the
        restore and raises :class:`WriteDuringRollbackError`. The removals the batch
        asked for are dropped. A second call raises :class:`JudgeReusedError`: a
        judge serves one batch.
        """
        self._settle()
        self._phase = "rolling_back"
        self._removals.clear()
        try:
            touched = list(self._touched.values())
            for entry in reversed(touched):
                entry.first.restore()
            for entry in touched:
                entry.first.element.announce_restored(entry.props)
        finally:
            self._phase = "settled"

    def _settle(self) -> None:
        if self._phase != "open":
            msg = "a batch judge settles once: its batch is committed or undone already"
            raise JudgeReusedError(msg)
        self._phase = "settled"

    def _require_not_rolling_back(self, what: str) -> None:
        if self._phase == "rolling_back":
            msg = f"{what} was made while a rollback was announcing what it restored"
            raise WriteDuringRollbackError(msg)

    def _entry_of(self, element: Element) -> _Written:
        key = id(element)
        entry = self._touched.get(key)
        if entry is None:
            entry = self._touched[key] = _Written(ElementCheckpoint(element))
        return entry
