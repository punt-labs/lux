"""SubmissionGate — the single pre-install rejection check for a scene tree.

A submitted tree must clear three tree-level gates before the Hub installs it:
every element self-validates (``ElementTreeValidator``), none nests past the wire
cap (``NestingCap``), and no named element id repeats (``DuplicateIdScanner``).
This facade runs all three and returns the first agent-facing rejection reason,
or ``None`` when the tree is clean and may be installed.

One entry point means a front door (the ``show`` tool, an applet client) asks
"may I install this?" and an invalid tree is never partially installed or rendered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.id_uniqueness import DuplicateIdScanner
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.domain.validation_walk import ElementTreeValidator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.ids import SceneId

__all__ = ["SubmissionGate"]


@final
class SubmissionGate:
    """Runs every pre-install gate and reports the first rejection reason.

    Stateless. ``first_rejection`` returns ``None`` for a clean tree — the
    "install me" contract — else an agent-facing string naming the first problem.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def first_rejection(self, scene_id: SceneId, roots: Sequence[object]) -> str | None:
        """Return why ``roots`` may not be installed, or ``None`` if it may."""
        report = ElementTreeValidator().validate_tree(roots)
        if not report.ok:
            return report.describe()
        duplicate = DuplicateIdScanner().first_duplicate(scene_id, roots)
        if duplicate is None:
            return NestingCap().refusal(roots)
        return (
            f"duplicate element id {str(duplicate.element_id)!r} appears "
            f"more than once; every element id in a scene must be unique"
        )
