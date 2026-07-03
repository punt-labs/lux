"""Frame-budget smoke for the Text render path.

A per-frame smoke that exercises the Element ABC template-method
``render()`` over a modest scene (10 ``TextElement`` instances) and
asserts the mean per-frame cost stays under a 2 ms budget. Measured
cost on the dispatch path is ~0.28 ms/frame; the 2 ms ceiling gives
roughly 7x headroom for slow CI without letting a 10x algorithmic
regression slip past.

Uses ``RecordingRenderer`` so timing is deterministic — no GL context,
no ImGui, no I/O beyond an append-only JSONL log under a tempdir.
That isolates the dispatch path (template method → factory call →
``renderer.render()``) from any GPU/driver variance and makes the
budget a guard against algorithmic regressions in the ABC layer.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Final

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers import RecordingLog, RecordingRendererFactory

_FRAMES: Final[int] = 60
_ELEMENTS_PER_FRAME: Final[int] = 10
# 2 ms / frame == ~7x headroom over the ~0.28 ms measured dispatch cost.
_BUDGET_SECONDS: Final[float] = 0.002


def _emit(_msg: object) -> None:
    """No-op emit channel for the leaf Text elements."""


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
