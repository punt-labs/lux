"""StageTimes — the stages a click spent time in, and the line reporting them.

A click is a walk: it arrives, it answers, it loads, it pushes. What this keeps
is that walk in the order it happened, plus one thing the figures cannot say on
their own — what the answer *was*. Answering in 28 ms with a board the applet
already had and answering in 28 ms with the word "Loading" are the same figure
and different clicks, so the answer says which it was.

It all goes out as one line, because its reader is a user who has been asked what
happened: pasting the line answers it.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.figure import Figure

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ["ANSWERED", "StageTimes"]

# The stage a click's budget is written for: its visible answer. Shared with the
# clock that holds that budget, which is what opens the stage.
ANSWERED = "answered"

# The whole wait, reported as the last figure on the line. It is not a stage —
# it is the click's own clock, so it covers any time spent between stages too.
_TOTAL = "total"


@final
class StageTimes:
    """One click's figures: each stage in the order it was spent, and the total."""

    _open: str
    _said: dict[str, str]
    _stages: dict[str, float]
    _started: float
    __slots__ = ("_open", "_said", "_stages", "_started")

    def __new__(cls) -> Self:
        """Start the walk here — where the click arrived, not where it is served."""
        self = super().__new__(cls)
        self._started = time.perf_counter()
        # Insertion order is the order the click spent its time, which is what
        # the reported line is: a walk through the click from arrival to board.
        self._stages = {}
        # What a stage had to say about itself, for the stages that had anything.
        self._said = {}
        # Which stage is being timed right now, so a note lands on the one that
        # earned it. Nothing is open between stages.
        self._open = ""
        return self

    @contextmanager
    def timing(self, name: str) -> Generator[None]:
        """Time one stage of the click's servicing and record it under ``name``.

        The duration is kept whether the stage returned or raised, because a
        stage that ran for thirty seconds and then failed is the one worth
        reading. It is also the open stage while it runs, so whatever it says
        about itself is attributed to it rather than to the click at large.
        """
        began, outer = time.perf_counter(), self._open
        self._open = name
        try:
            yield
        finally:
            self._stages[name] = self._since(began)
            self._open = outer

    def note(self, said: str) -> None:
        """Say what the stage now being timed did, beside its figure.

        No stage is named because the one being timed is the only one that can be
        talking. Said outside any stage, it belongs to none and is not reported.
        """
        self._said[self._open] = said

    @property
    def answered_ms(self) -> float:
        """How long the answer took — the figure the budget is written about.

        A click that ended before it was answered spent no time answering, and so
        has no budget to have broken.
        """
        return self._stages.get(ANSWERED, 0.0)

    def line(self) -> str:
        """Every figure, in the order the click spent it, ending with the total.

        A click that ended early reports only the stages it reached, which is
        itself how far it got. The total joins the stages rather than standing
        apart from them: it is the last figure a reader wants and reads as one
        more phrase in the walk.
        """
        figures = self._stages | {_TOTAL: self._since(self._started)}
        return ", ".join(
            Figure(name, ms, self._said.get(name, "")).text()
            for name, ms in figures.items()
        )

    @staticmethod
    def _since(began: float) -> float:
        """Milliseconds since a mark taken off the same clock."""
        return (time.perf_counter() - began) * 1000.0
