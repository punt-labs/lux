"""Forward each first-paint duration without a scene identifier."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

from punt_lux.display import paint_telemetry
from punt_lux.display.paint_clock import PaintClock

if TYPE_CHECKING:
    import pytest


def test_report_swap_records_only_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    record = Mock()
    monkeypatch.setattr(paint_telemetry, "record_first_paint", record)
    clock = PaintClock(iter((0.0, 0.125, 0.25)).__next__)
    clock.received("first")
    clock.received("second")
    clock.painted("first")
    clock.painted("second")

    paint_telemetry.PaintTelemetry.report_swap(clock)

    assert sorted(call.args for call in record.call_args_list) == [(125.0,), (250.0,)]
    assert all(not call.kwargs for call in record.call_args_list)
