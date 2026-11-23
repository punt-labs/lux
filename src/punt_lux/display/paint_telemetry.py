"""Report first-paint timings through Lux's usage facade."""

from __future__ import annotations

from typing import final

from punt_lux.display.paint_clock import PaintClock as PaintClock
from punt_lux.kernel.usage import record_first_paint


@final
class PaintTelemetry:
    """Report durations for the scenes first painted by a clock."""

    @staticmethod
    def report_swap(clock: PaintClock) -> None:
        """Record the first-paint latencies for a completed swap."""
        for elapsed_ms in clock.swapped():
            record_first_paint(elapsed_ms)
