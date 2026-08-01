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

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ["StageTimes"]

# The stage a click's budget is written for: its visible answer. It is also the
# only stage that has anything to say about itself.
_ANSWERED = "answered"

# The whole wait, reported as the last figure on the line. It is not a stage —
# it is the click's own clock, so it covers any time spent between stages too.
_TOTAL = "total"


@final
class StageTimes:
    """One click's figures: each stage in the order it was spent, and the total."""

    _answer: str
    _stages: dict[str, float]
    _started: float
    __slots__ = ("_answer", "_stages", "_started")

    def __new__(cls, started: float) -> Self:
        self = super().__new__(cls)
        self._started = started
        # Insertion order is the order the click spent its time, which is what
        # the reported line is: a walk through the click from arrival to board.
        self._stages = {}
        # Nothing said about the answer is the ordinary answer; a click that
        # answered with something worth naming says so.
        self._answer = ""
        return self

    @classmethod
    def begun(cls) -> Self:
        """Start the walk here — where the click arrived, not where it is served."""
        return cls(time.perf_counter())

    @contextmanager
    def answering(self) -> Generator[None]:
        """Time the click's visible answer — the one stage held to a budget."""
        with self.timing(_ANSWERED):
            yield

    @contextmanager
    def timing(self, name: str) -> Generator[None]:
        """Time one stage of the click's servicing and record it under ``name``.

        The duration is kept whether the stage returned or raised, because a
        stage that ran for thirty seconds and then failed is the one worth
        reading.
        """
        began = time.perf_counter()
        try:
            yield
        finally:
            self._stages[name] = self._since(began)

    def answered_with(self, note: str) -> None:
        """Say what the click's visible answer was, beside how long it took."""
        self._answer = note

    @property
    def answered_ms(self) -> float:
        """How long the answer took — the figure the budget is written about.

        A click that ended before it was answered spent no time answering, and so
        has no budget to have broken.
        """
        return self._stages.get(_ANSWERED, 0.0)

    def line(self) -> str:
        """Every figure, in the order the click spent it, ending with the total.

        A click that ended early reports only the stages it reached, which is
        itself how far it got. The total joins the stages rather than standing
        apart from them: it is the last figure a reader wants and reads as one
        more phrase in the walk.
        """
        figures = self._stages | {_TOTAL: self._since(self._started)}
        return ", ".join(self._figure(name, ms) for name, ms in figures.items())

    def _figure(self, name: str, ms: float) -> str:
        """One stage's figure, and whatever that stage had to say about itself."""
        if name == _ANSWERED and self._answer:
            return f"{name} {ms:.0f} ms ({self._answer})"
        return f"{name} {ms:.0f} ms"

    @staticmethod
    def _since(began: float) -> float:
        """Milliseconds since a mark taken off the same clock."""
        return (time.perf_counter() - began) * 1000.0
