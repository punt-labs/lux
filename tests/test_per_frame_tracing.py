"""What the per-frame render path may log: nothing, once per element per frame.

ImGui repaints every element of the live scene on every frame, so a single log
line on that path is not a line — it is a line times sixty times the element
count, every second the window is open. The display's log is where a click or a
crash is read; a per-frame trace buries both. This holds the render path to
emitting nothing per call, and holds ``trace`` to the event-driven paths where
one line means one thing happened.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display import renderers
from punt_lux.display.server import DisplayServer
from punt_lux.tracing import trace

if TYPE_CHECKING:
    import pytest


def _is_traced(owner: type, method_name: str) -> bool:
    """Report whether ``owner.method_name`` is wrapped by ``trace``.

    ``trace`` applies ``functools.wraps``, which records the undecorated
    function on ``__wrapped__`` — the wrapping is visible without calling it,
    so this needs no GL context.
    """
    return hasattr(getattr(owner, method_name), "__wrapped__")


def test_no_renderer_logs_on_the_per_frame_path() -> None:
    """Every ``render`` runs once per element per frame; none of them may log."""
    traced = [
        name
        for name in renderers.__all__
        if _is_traced(getattr(renderers, name), "render")
    ]
    assert traced == [], (
        f"these renderers log once per element per frame: {traced}. "
        "Per-frame tracing floods the display log; trace an event instead."
    )


def test_the_paint_loop_calls_render_without_a_traced_wrapper() -> None:
    """The paint loop dispatches straight to the element's own ``render``.

    The wrapper it used to call through existed only to carry the trace; with
    the trace gone there is nothing for it to do, and reinstating it would put
    a per-element-per-frame call site back where the flood started.
    """
    assert not hasattr(DisplayServer, "_paint_element")


def test_trace_still_reports_an_event_driven_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``trace`` is kept, not deleted — one line per event is what it is for."""

    @trace
    def deliver(count: int) -> int:
        return count

    with caplog.at_level(logging.DEBUG):
        assert deliver(3) == 3

    assert "deliver called args=(3,)" in caplog.text
