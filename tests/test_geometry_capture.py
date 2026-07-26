"""``GeometryCapture`` — the render-tier surface that does not read ImGui.

The ImGui reads (``record_window``/``record_frame`` → ``get_window_pos``) need a
live window and are verified at the demo gate; here we cover the scene-scoping
and recorder handoff that the query path depends on.
"""

from __future__ import annotations

from punt_lux.display.geometry import GeometryRecorder
from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.protocol.geometry import Rect


def test_recorder_is_a_recorder() -> None:
    assert isinstance(GeometryCapture().recorder, GeometryRecorder)


def test_complete_promotes_through_to_the_recorder() -> None:
    capture = GeometryCapture()
    # Record straight on the wrapped recorder (bypassing the ImGui read), then
    # promote through the capture — the snapshot must reflect it.
    rect = Rect(x=1.0, y=2.0, width=3.0, height=4.0)
    capture.enter_scene("s1")
    capture.recorder.record_element("s1", "e", rect, 0)
    capture.complete()
    geom = capture.recorder.snapshot().element_for("s1", "e")
    assert geom is not None
    assert geom.rect == rect
