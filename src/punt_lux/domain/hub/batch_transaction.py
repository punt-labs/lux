"""BatchTransaction -- an agent's batch of field writes, committed as one unit.

Every write a batch makes, its own and those the observers it wakes make, stands or
none does. The batch was judged whole before this runs, so each realization's own write
is let through by the :class:`~punt_lux.domain.hub.batch_judge.BatchJudge`, and every
other write meets the seam's own judge. When anything fails, a refused observer write
included, every element written is put back and its observers told. When everything
committed, the final state of each element written is measured against the cap once
more, since each write was judged when it was made and not against what the writes
after it would leave.
"""

from __future__ import annotations

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

    def run(self, realizations: Sequence[FieldRealization]) -> None:
        """Commit every realization, or put every element written back and raise."""
        judge = BatchJudge(self._admit, [r.write() for r in realizations])
        with HandlerWrites.judged(judge):
            try:
                for realization in realizations:
                    realization.commit()
                self._within_cap(judge.written)
            except Exception:
                judge.roll_back()
                raise

    def commit(
        self, realizations: Sequence[FieldRealization]
    ) -> WriteRejected | None:  # PY-TS-14 OK: None is a batch that stood
        """Run the batch; why the judge refused it, when it rolled back."""
        try:
            self.run(realizations)
        except WriteRefusedError as exc:
            return WriteRejected(str(exc))
        return None
