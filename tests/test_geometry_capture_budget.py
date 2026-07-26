"""Geometry capture is cheap enough to run every frame at 60fps.

The recorder builds one geometry value per captured element (rect plus paint
sequence and stack index) and swaps two dicts at frame end — no I/O, no
allocation storm. This smoke measures that per-frame cost against a deliberately
loose ceiling: the guard catches a catastrophic blow-up (an accidental O(n^2),
per-element I/O, an unbounded copy), not a small regression. Measured cost for 50
captured elements is ~40 us/frame — ~0.24% of the 16.67 ms 60fps budget, up from
~25 us before Z-order added the value construction — so the ceiling sits far
above it and never flakes under load. The assertion is machine-sensitive, so it
lives in the slow class, outside the gate.
"""

from __future__ import annotations

import time

import pytest

from punt_lux.display.geometry import ElementRef, GeometryRecorder
from punt_lux.protocol.geometry import Rect

# Leaves are captured per element now, so 50 painted elements a frame is a
# realistic mid-size scene. The ceiling is ~50x the measured ~40 us, loose enough
# to never flake yet tight enough to catch a blow-up.
_ELEMENTS_PER_FRAME = 50
_FRAMES = 2_000
_PER_FRAME_CEILING_S = 2.0e-3


@pytest.mark.slow
def test_capture_cost_stays_a_fraction_of_the_frame_budget() -> None:
    rect = Rect(x=1.0, y=2.0, width=100.0, height=20.0)
    refs = [ElementRef(f"e{i}", "text") for i in range(_ELEMENTS_PER_FRAME)]
    recorder = GeometryRecorder()

    start = time.perf_counter()
    for _ in range(_FRAMES):
        for index, ref in enumerate(refs):
            recorder.record_element("scene", ref, rect, index)
        recorder.record_frame("win", rect, 0)
        recorder.complete()
    per_frame = (time.perf_counter() - start) / _FRAMES

    assert per_frame < _PER_FRAME_CEILING_S
