"""``GeometryRecorder``/``GeometrySnapshot`` — capture, promotion, readback.

These drive the recorder with injected rects — the same rects the render loop
would read from ImGui — so the two acceptance stories (a painted element reports
its actual width; a window's rect survives a re-push) are provable headless,
without a live display.
"""

from __future__ import annotations

from punt_lux.display.geometry import GeometryRecorder, GeometrySnapshot
from punt_lux.protocol.geometry import Rect


def test_empty_snapshot_reports_no_rects() -> None:
    snap = GeometrySnapshot.empty()
    assert snap.rect_for("scene", "elem") is None
    assert snap.frame_rect("frame") is None


def test_recorded_element_reads_back_after_complete() -> None:
    rec = GeometryRecorder()
    rec.record_element("scene", "btn", Rect(x=5.0, y=6.0, width=80.0, height=24.0))
    rec.complete()
    assert rec.snapshot().rect_for("scene", "btn") == Rect(
        x=5.0, y=6.0, width=80.0, height=24.0
    )


def test_building_rects_are_invisible_until_complete() -> None:
    rec = GeometryRecorder()
    rec.record_element("scene", "btn", Rect(x=0.0, y=0.0, width=10.0, height=10.0))
    # No complete() yet — the snapshot is still the empty last-completed frame.
    assert rec.snapshot().rect_for("scene", "btn") is None


def test_needle_modal_reports_its_actual_painted_width() -> None:
    # The needle defect: a modal auto-sized to ~20px would have been caught by a
    # geometry read. Record the painted width and assert it reads back.
    rec = GeometryRecorder()
    rec.record_element("dlg", "needle", Rect(x=100.0, y=100.0, width=20.0, height=40.0))
    rec.complete()
    rect = rec.snapshot().rect_for("dlg", "needle")
    assert rect is not None
    assert rect.width == 20.0


def test_window_rect_survives_a_re_push() -> None:
    # The drag-survival demo: a user drags a window to (400, 300); the Hub
    # re-pushes the whole UI. Because the drag persists Display-side, the next
    # painted frame captures the same rect — geometry reads the dragged position
    # both before and after the re-push, with no human eye.
    dragged = Rect(x=400.0, y=300.0, width=320.0, height=200.0)

    rec = GeometryRecorder()
    rec.record_frame("win", dragged)
    rec.complete()
    before = rec.snapshot().frame_rect("win")

    # A whole-UI re-push re-paints the window at its persisted dragged position.
    rec.record_frame("win", dragged)
    rec.complete()
    after = rec.snapshot().frame_rect("win")

    assert before == after == dragged


def test_element_ids_are_scoped_per_scene() -> None:
    rec = GeometryRecorder()
    rec.record_element("a", "submit", Rect(x=0.0, y=0.0, width=10.0, height=10.0))
    rec.record_element("b", "submit", Rect(x=99.0, y=99.0, width=50.0, height=50.0))
    rec.complete()
    snap = rec.snapshot()
    assert snap.rect_for("a", "submit") == Rect(x=0.0, y=0.0, width=10.0, height=10.0)
    assert snap.rect_for("b", "submit") == Rect(x=99.0, y=99.0, width=50.0, height=50.0)


def test_complete_forgets_the_prior_frame() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "gone", Rect(x=0.0, y=0.0, width=1.0, height=1.0))
    rec.complete()
    # The next frame paints nothing; the element that vanished is absent.
    rec.complete()
    assert rec.snapshot().rect_for("s", "gone") is None


def test_to_wire_carries_scene_elements_and_frame_rect() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "title", Rect(x=8.0, y=8.0, width=200.0, height=18.0))
    rec.record_element("other", "hidden", Rect(x=0.0, y=0.0, width=5.0, height=5.0))
    rec.record_frame("f", Rect(x=0.0, y=0.0, width=800.0, height=600.0))
    rec.complete()
    wire = rec.snapshot().to_wire("s", "f")
    assert wire == {
        "elements": {"title": {"x": 8.0, "y": 8.0, "width": 200.0, "height": 18.0}},
        "frame": {"x": 0.0, "y": 0.0, "width": 800.0, "height": 600.0},
    }


def test_to_wire_frame_is_null_when_frame_not_painted() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "title", Rect(x=1.0, y=1.0, width=2.0, height=2.0))
    rec.complete()
    wire = rec.snapshot().to_wire("s", frame_id=None)
    assert wire["frame"] is None
    assert wire["elements"] == {
        "title": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0}
    }
