"""BatchJudge -- the judge in force while a batch of agent writes is committed.

A batch is judged whole before its first commit, so each write the batch itself makes
is already judged and is let through here, once: the write is the element and the very
patch mapping the batch holds for it, by identity. Every other write, such as one an
observer of an earlier target makes to a later target, goes to the seam's own judge
like any other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.handler_writes import WriteJudge

__all__ = ["BatchJudge"]


@final
class BatchJudge:
    """Lets each pre-judged write of the batch through once, and judges the rest."""

    _admit: WriteJudge
    _unspent: list[tuple[Element, Mapping[str, object]]]
    __slots__ = ("_admit", "_unspent")

    def __new__(
        cls,
        admit: WriteJudge,
        writes: Iterable[tuple[Element, Mapping[str, object]]],
    ) -> Self:
        self = super().__new__(cls)
        self._admit = admit
        self._unspent = list(writes)
        return self

    def __call__(self, element: Element, patch: Mapping[str, object]) -> None:
        for index, (target, fields) in enumerate(self._unspent):
            if target is element and fields is patch:
                del self._unspent[index]
                return
        self._admit(element, patch)
