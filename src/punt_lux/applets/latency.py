"""ClickLatency — the clock a click starts, and the budget it is held to.

A menu entry has to launch in the time a user reads as instant, and that is a
number, not an aspiration, so it is measured on every click rather than assumed.
The clock starts where the click arrives — on the receive loop, before the hop to
the worker — so the hop is inside the number rather than hidden beside it.

The visible answer is the only stage held to that budget, but it is not the whole
click: the work behind it is what the user waits through while the window says
"Loading" — or does not wait through at all, when the answer was a board they can
already read. Every stage of it is timed and reported, in
:class:`~punt_lux.applets.stage_times.StageTimes`, which is where the line and
its figures live. What lives here is the contract: what a click owes the user,
and what happens when it is not met.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.stage_times import StageTimes

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

logger = logging.getLogger(__name__)

__all__ = ["ClickLatency"]

# What a click has to answer within to read as instant. It is the reason the
# servicing is split in two: the visible response is measured against this, and
# the work behind it is not.
_RESPONSE_BUDGET_MS = 100.0


@final
class ClickLatency:
    """One click's clock, and the one line that says how it went.

    What the answered stage measures is the contract: a click must produce a
    visible response inside :data:`_RESPONSE_BUDGET_MS`. The clock therefore
    starts where the click arrives — on the receive loop, before the hop to the
    worker — so the hop is inside the number rather than hidden beside it. The
    stages after the answer are under no budget, but they are the rest of the
    user's wait, so they are measured on the same clock.
    """

    _callback_id: str
    _times: StageTimes
    __slots__ = ("_callback_id", "_times")

    def __new__(cls, callback_id: str) -> Self:
        self = super().__new__(cls)
        self._callback_id = callback_id
        self._times = StageTimes.begun()
        return self

    def answering(self) -> AbstractContextManager[None]:
        """Time the click's visible answer — the one stage held to the budget."""
        return self._times.answering()

    def stage(self, name: str) -> AbstractContextManager[None]:
        """Time one stage of the click's servicing and record it under ``name``."""
        return self._times.timing(name)

    def answered_with(self, note: str) -> None:
        """Say what the click's visible answer was, on the line that reports it.

        A click answered with the board the applet already had is a different
        click from one answered with a placeholder: in the first the user is
        reading their issues while the fresh ones load, in the second they are
        reading the word "Loading". The figures are the same and cannot tell them
        apart, so the answer says which it was.
        """
        self._times.answered_with(note)

    def report(self) -> None:
        """Log where this click's time went, and whether it owed the user faster.

        One line rather than one per stage, because its reader is a user who has
        been asked what happened — pasting the line answers it. A click that
        broke the budget says so on the same line, at a level this process logs
        at whether or not anyone asked for the ordinary ones.
        """
        if self._times.answered_ms > _RESPONSE_BUDGET_MS:
            logger.warning(
                "click %s: %s — answered over the %.0f ms budget",
                self._callback_id,
                self._line(),
                _RESPONSE_BUDGET_MS,
            )
            return
        logger.info("click %s: %s", self._callback_id, self._line())

    def _line(self) -> str:
        """This click's figures, as the one line both reports are built around."""
        return self._times.line()
