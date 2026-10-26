"""BatchJudge -- the judge in force while a batch of agent writes is committed.

A batch is judged whole before its first commit, so the first write each target
receives is already judged and is let through here. Every later write, such as one an
observer of a target makes in turn, goes to the seam's own judge like any other.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.handler_writes import WriteJudge

__all__ = ["BatchJudge"]


@final
class BatchJudge:
    """Lets each batch target's first write through, and judges the rest."""

    _admit: WriteJudge
    _unjudged: Counter[int]
    __slots__ = ("_admit", "_unjudged")

    def __new__(cls, admit: WriteJudge, targets: Iterable[object]) -> Self:
        self = super().__new__(cls)
        self._admit = admit
        self._unjudged = Counter(id(target) for target in targets)
        return self

    def __call__(self, element: Element, patch: Mapping[str, object]) -> None:
        if self._unjudged[id(element)] > 0:
            self._unjudged[id(element)] -= 1
            return
        self._admit(element, patch)
