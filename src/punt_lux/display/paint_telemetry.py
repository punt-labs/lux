"""Report first-paint timings through Lux's usage facade."""

from __future__ import annotations

from punt_lux.display.paint_clock import PaintClock as PaintClock
from punt_lux.usage import record_first_paint


def report_swap(clock: PaintClock) -> None:
    """Record the latencies of the scenes first painted in a completed swap."""
    for elapsed_ms in clock.swapped():
        record_first_paint(elapsed_ms)
