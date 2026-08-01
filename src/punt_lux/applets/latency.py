"""ClickLatency — the clock a click starts, and where the click's time went.

A menu entry has to launch in the time a user reads as instant, and that is a
number, not an aspiration, so it is measured on every click rather than assumed.
The clock starts where the click arrives — on the receive loop, before the hop to
the worker — so the hop is inside the number rather than hidden beside it.

The visible answer is the only stage held to that budget, but it is not the whole
click: the query, the build, and the push behind it are what the user waits
through while the window says "Loading". Each is timed, and all of them go out on
one line, so a user who pastes that line has already said where the time went and
nobody has to ask which stage was the slow one.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

__all__ = ["ClickLatency"]

# What a click has to answer within to read as instant. It is the reason the
# servicing is split in two: the visible response is measured against this, and
# the work behind it is not.
_RESPONSE_BUDGET_MS = 100.0

# The stage that budget is written for: the click's visible answer.
_ANSWERED = "answered"

# The whole wait, reported as the last figure on the line. It is not a stage —
# it is the click's own clock, so it covers any time spent between stages too.
_TOTAL = "total"


@final
class ClickLatency:
    """One click's clock: the stages it spent time in, and the line reporting them.

    What the answered stage measures is the contract: a click must produce a
    visible response inside :data:`_RESPONSE_BUDGET_MS`. The clock therefore
    starts where the click arrives — on the receive loop, before the hop to the
    worker — so the hop is inside the number rather than hidden beside it. The
    stages after the answer are under no budget, but they are the rest of the
    user's wait, so they are measured on the same clock.
    """

    _callback_id: str
    _started: float
    _stages: dict[str, float]
    __slots__ = ("_callback_id", "_stages", "_started")

    def __new__(cls, callback_id: str) -> Self:
        self = super().__new__(cls)
        self._callback_id = callback_id
        self._started = time.perf_counter()
        # Insertion order is the order the click spent its time, which is what
        # the reported line is: a walk through the click from arrival to board.
        self._stages = {}
        return self

    @contextmanager
    def answering(self) -> Generator[None]:
        """Time the click's visible answer — the one stage held to the budget."""
        with self.stage(_ANSWERED):
            yield

    @contextmanager
    def stage(self, name: str) -> Generator[None]:
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

    def report(self) -> None:
        """Log where this click's time went: one line, in the order it was spent.

        One line rather than one per stage, because its reader is a user who has
        been asked what happened — pasting the line answers it. A click that
        ended early reports only the stages it reached, which is itself how far
        it got, and the total covers the whole wait either way, including
        whatever was spent between stages.
        """
        # A click that failed before it was answered spent no time answering, and
        # so has no budget to have broken.
        if self._stages.get(_ANSWERED, 0.0) > _RESPONSE_BUDGET_MS:
            logger.warning(
                "click %s: %s — answered over the %.0f ms budget",
                self._callback_id,
                self._line(),
                _RESPONSE_BUDGET_MS,
            )
            return
        logger.info("click %s: %s", self._callback_id, self._line())

    def _line(self) -> str:
        """The stages and the total, in order, as the figures they are reported as.

        The total joins the stages rather than standing apart from them: it is
        the last figure a reader wants and reads as one more phrase in the walk.
        """
        figures = self._stages | {_TOTAL: self._since(self._started)}
        return ", ".join(f"{name} {ms:.0f} ms" for name, ms in figures.items())

    @staticmethod
    def _since(began: float) -> float:
        """Milliseconds since a mark taken off the same clock."""
        return (time.perf_counter() - began) * 1000.0
