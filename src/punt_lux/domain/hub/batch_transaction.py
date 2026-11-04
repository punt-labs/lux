"""BatchTransaction -- an agent's batch of field writes, committed as one unit.

Every write a batch makes, its own and those the observers it wakes make, stands or
none does; so does every removal it asks for (a dialog's own dismissal), which is
carried out once everything else stood. The batch was judged whole before this runs,
so each realization's own write is let through by the
:class:`~punt_lux.domain.hub.batch_judge.BatchJudge`, and every other write meets the
seam's own judge. When anything fails, a refused observer write included, every
element written is put back and its observers told. When everything committed, the
final state of each element written is measured against the cap once more, since each
write was judged when it was made and not against what the writes after it would leave.

A transaction opened inside one that is in force joins it: it judges and records
nothing of its own, and what it writes stands or falls with the outer transaction. A
refusal inside it is raised for the outer transaction to roll back, not returned.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.handler_writes import HandlerWrites, WriteRefusedError
from punt_lux.domain.hub.batch_judge import BatchJudge
from punt_lux.domain.hub.write_result import WriteRejected

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.handler_writes import WriteJudge
    from punt_lux.domain.hub.field_realization import FieldRealization

__all__ = ["BatchTransaction"]


@final
class BatchTransaction:
    """Commits realizations under one judge, and undoes them all when one fails."""

    _admit: WriteJudge
    _within_cap: Callable[[Sequence[Element]], None]
    __slots__ = ("_admit", "_within_cap")

    def __new__(
        cls, admit: WriteJudge, within_cap: Callable[[Sequence[Element]], None]
    ) -> Self:
        self = super().__new__(cls)
        self._admit = admit
        self._within_cap = within_cap
        return self

    # PY-TS-14 OK: None is a batch that stood.
    def run(self, realizations: Sequence[FieldRealization]) -> WriteRejected | None:
        """Commit every realization as one unit; why the judge refused it, if it did.

        On a refusal, or any other failure, every element written is put back and its
        observers told. A refusal is returned as the agent's ``WriteRejected``; any
        other failure is raised once the undo is done.
        """
        judge = BatchJudge(self._admit, [r.write() for r in realizations])
        refusal = self._attempt(judge, partial(self._commit_all, realizations))
        return None if refusal is None else WriteRejected(str(refusal))

    def run_or_raise(self, realizations: Sequence[FieldRealization]) -> None:
        """Commit every realization as one unit, raising the refusal the judge made.

        A store-level write has no ``WriteRejected`` to carry a refusal, so the very
        error the judge raised leaves, once every element written is put back.
        """
        judge = BatchJudge(self._admit, [r.write() for r in realizations])
        refusal = self._attempt(judge, partial(self._commit_all, realizations))
        if refusal is not None:
            raise refusal

    # PY-TS-14 OK: None is a handler whose writes and removals stood.
    def run_handler(self, handle: Callable[[], None]) -> WriteRefusedError | None:
        """Run a handler whose every write and removal stands, or none does.

        The handler's own writes, and those the observers they wake make, are judged
        as they are made and measured once more when the handler has returned. A
        refusal anywhere puts every element written back, observers' state included,
        drops the removals asked for, and is returned for the caller to report; any
        other failure is raised once the undo is done.
        """
        return self._attempt(BatchJudge(self._admit, []), handle)

    # PY-TS-14 OK: None is a transaction that stood.
    def _attempt(
        self, judge: BatchJudge, work: Callable[[], None]
    ) -> WriteRefusedError | None:
        """Run ``work`` under ``judge``; the refusal that rolled it back, if any."""
        if HandlerWrites.in_transaction():
            work()  # joins the transaction in force: it records, it settles
            return None
        with HandlerWrites.judged(judge):
            try:
                work()
                self._within_cap(judge.written)
            except WriteRefusedError as exc:
                judge.roll_back()
                return exc
            except Exception:
                judge.roll_back()
                raise
        judge.commit()  # outside the scope: a removal is an ordinary one again
        return None

    @staticmethod
    def _commit_all(realizations: Sequence[FieldRealization]) -> None:
        for realization in realizations:
            realization.commit()
