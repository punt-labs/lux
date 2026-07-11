"""Frame-budget smoke for the Text render path.

A per-frame smoke that exercises the Element ABC template-method
``render()`` over a modest scene (10 ``TextElement`` instances) and
asserts the mean per-frame cost stays under a deliberately loose
budget. Measured cost on the dispatch path is ~0.28 ms/frame.

This is a pathological/regression smoke guard, not a precise latency
gate. The budget is an absolute wall-clock bound on a pure-Python,
no-I/O, no-GL dispatch loop, and such a bound tracks machine load —
scheduler preemption, CPU frequency scaling, GC pauses, noisy CI
neighbors — far more than it tracks algorithmic cost. A tight bound
would fail deterministically under load without any code regression,
so the budget is set an order of magnitude above the measured cost:
it catches a catastrophic blow-up while staying immune to load.

Because the bound is machine-sensitive rather than code-sensitive,
the test is marked ``slow`` and lives outside the default serial gate.

Uses ``RecordingRenderer`` so the work is deterministic — no GL
context, no ImGui, no I/O beyond an append-only JSONL log under a
tempdir. That isolates the dispatch path (template method → factory
call → ``renderer.render()``) from any GPU/driver variance.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Final

import pytest

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory

_FRAMES: Final[int] = 60
_ELEMENTS_PER_FRAME: Final[int] = 10
# 20 ms / frame — an order of magnitude above the ~0.28 ms measured cost.
# Loose on purpose: an absolute wall-clock bound tracks machine load, not code.
_BUDGET_SECONDS: Final[float] = 0.020


def _emit(_msg: object) -> None:
    """No-op emit channel for the leaf Text elements."""


@pytest.mark.slow
def test_ten_text_elements_render_under_budget_per_frame() -> None:
    with tempfile.TemporaryDirectory(prefix="lux-perf-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "frame_budget.jsonl")
        factory = RecordingRendererFactory(log)
        elements = tuple(
            TextElement(
                renderer_factory=factory,
                emit=_emit,
                id=f"t{i}",
                content=f"row-{i}",
            )
            for i in range(_ELEMENTS_PER_FRAME)
        )

        start = time.perf_counter()
        for _ in range(_FRAMES):
            for elem in elements:
                elem.render()
        elapsed = time.perf_counter() - start

        mean_per_frame = elapsed / _FRAMES
        budget_ms = _BUDGET_SECONDS * 1000
        assert mean_per_frame < _BUDGET_SECONDS, (
            f"mean per-frame {mean_per_frame * 1000:.2f} ms "
            f"exceeds {budget_ms:.0f} ms budget over {_FRAMES} frames"
        )
