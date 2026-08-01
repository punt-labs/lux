"""ClickLatency — the clock a click starts, and the gap it reports.

A menu entry has to launch in the time a user reads as instant, and that is a
number, not an aspiration, so it is measured on every click rather than assumed.
The clock starts where the click arrives — on the receive loop, before the hop to
the worker — so the hop is inside the number rather than hidden beside it.
"""

from __future__ import annotations

import logging
import time
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["ClickLatency"]

# What a click has to answer within to read as instant. It is the reason the
# servicing is split in two: the visible response is measured against this, and
# the work behind it is not.
_RESPONSE_BUDGET_MS = 100.0


@final
class ClickLatency:
    """The clock a click starts, and the gap it reports when the answer lands.

    What is being measured is the contract: a click must produce a visible
    response inside :data:`_RESPONSE_BUDGET_MS`. The clock therefore starts where
    the click arrives — on the receive loop, before the hop to the worker — so the
    hop is inside the number rather than hidden beside it.
    """

    _started: float
    __slots__ = ("_started",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._started = time.perf_counter()
        return self

    def elapsed_ms(self) -> float:
        """Milliseconds since the click arrived."""
        return (time.perf_counter() - self._started) * 1000.0

    def report(self, callback_id: str) -> None:
        """Log the click's visible-response latency against its budget."""
        elapsed = self.elapsed_ms()
        if elapsed > _RESPONSE_BUDGET_MS:
            logger.warning(
                "click %s answered in %.0f ms — over the %.0f ms budget",
                callback_id,
                elapsed,
                _RESPONSE_BUDGET_MS,
            )
            return
        logger.info("click %s answered in %.0f ms", callback_id, elapsed)
