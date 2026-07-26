"""``GeometryRecorder``/``GeometrySnapshot`` — capture, promotion, readback.

These drive the recorder with injected rects and stack indices — the same values
the render loop reads from ImGui — so the acceptance stories (a painted element
reports its actual width; a window's rect survives a re-push; overlapping things
report a comparable Z-order) are provable headless, without a live display.
"""

from __future__ import annotations

from punt_lux.display.geometry import GeometryRecorder, GeometrySnapshot
from punt_lux.protocol.geometry import Rect


def _rect(x: float = 0.0, y: float = 0.0, w: float = 10.0, h: float = 10.0) -> Rect:
    return Rect(x=x, y=y, width=w, height=h)


def test_empty_snapshot_reports_nothing_painted() -> None:
    snap = GeometrySnapshot.empty()
    assert snap.element_for("scene", "elem") is None
    assert snap.frame_for("frame") is None


def test_recorded_element_reads_back_after_complete() -> None:
    rec = GeometryRecorder()
    rec.record_element("scene", "btn", Rect(x=5.0, y=6.0, width=80.0, height=24.0), 0)
    rec.complete()
    geom = rec.snapshot().element_for("scene", "btn")
    assert geom is not None
    assert geom.rect == Rect(x=5.0, y=6.0, width=80.0, height=24.0)


def test_building_geometry_is_invisible_until_complete() -> None:
    rec = GeometryRecorder()
    rec.record_element("scene", "btn", _rect(), 0)
    # No complete() yet — the snapshot is still the empty last-completed frame.
    assert rec.snapshot().element_for("scene", "btn") is None


def test_needle_modal_reports_its_actual_painted_width() -> None:
    # The needle defect: a modal auto-sized to ~20px would have been caught by a
    # geometry read. Record the painted width and assert it reads back.
    rec = GeometryRecorder()
    rec.record_element(
        "dlg", "needle", Rect(x=100.0, y=100.0, width=20.0, height=40.0), 1
    )
    rec.complete()
    geom = rec.snapshot().element_for("dlg", "needle")
    assert geom is not None
    assert geom.rect.width == 20.0


def test_window_rect_survives_a_re_push() -> None:
    # The drag-survival demo: a user drags a window to (400, 300); the Hub
    # re-pushes the whole UI. Because the drag persists Display-side, the next
    # painted frame captures the same rect — geometry reads the dragged position
    # both before and after the re-push, with no human eye.
    dragged = Rect(x=400.0, y=300.0, width=320.0, height=200.0)

    rec = GeometryRecorder()
    rec.record_frame("win", dragged, 0)
    rec.complete()
    before = rec.snapshot().frame_for("win")

    # A whole-UI re-push re-paints the window at its persisted dragged position.
    rec.record_frame("win", dragged, 0)
    rec.complete()
    after = rec.snapshot().frame_for("win")

    assert before is not None
    assert after is not None
    assert before.rect == after.rect == dragged


def test_overlapping_elements_report_distinguishable_paint_sequence() -> None:
    # Two elements painted one after the other take successive sequence numbers,
    # so a caller can tell which drew on top when they overlap.
    rec = GeometryRecorder()
    rec.record_element("s", "under", _rect(), 0)
    rec.record_element("s", "over", _rect(x=5.0), 0)
    rec.complete()
    snap = rec.snapshot()
    under = snap.element_for("s", "under")
    over = snap.element_for("s", "over")
    assert under is not None
    assert over is not None
    assert over.paint_sequence > under.paint_sequence


def test_two_overlapping_leaves_report_distinct_sequence_and_intersecting_rects() -> (
    None
):
    # Two leaves painted over the same region: their sequence numbers order them
    # (later on top) and their rects intersect, so an overlap assertion is
    # decidable — the reason the operator ruled Z-order in.
    rec = GeometryRecorder()
    rec.record_element("s", "label", Rect(x=10.0, y=10.0, width=100.0, height=30.0), 0)
    rec.record_element("s", "badge", Rect(x=60.0, y=20.0, width=80.0, height=30.0), 0)
    rec.complete()
    snap = rec.snapshot()
    label = snap.element_for("s", "label")
    badge = snap.element_for("s", "badge")
    assert label is not None
    assert badge is not None
    assert badge.paint_sequence > label.paint_sequence
    # The two rects overlap horizontally (60..140 vs 10..110) and vertically.
    assert label.rect.x < badge.rect.x + badge.rect.width
    assert badge.rect.x < label.rect.x + label.rect.width
    assert label.rect.y < badge.rect.y + badge.rect.height
    assert badge.rect.y < label.rect.y + label.rect.height


def test_open_modal_window_stacks_above_the_frame_beneath_it() -> None:
    # An open modal begins after the frame under it, so ImGui gives it a higher
    # begin-order; the geometry reply reports that as a higher stack index.
    rec = GeometryRecorder()
    rec.record_frame("frame", _rect(w=800.0, h=600.0), 0)
    rec.record_element("frame", "confirm", _rect(w=200.0, h=100.0), 1)
    rec.complete()
    snap = rec.snapshot()
    frame = snap.frame_for("frame")
    modal = snap.element_for("frame", "confirm")
    assert frame is not None
    assert modal is not None
    assert modal.stack_index > frame.stack_index


def test_paint_sequence_restarts_each_frame() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "a", _rect(), 0)
    rec.record_element("s", "b", _rect(), 0)
    rec.complete()
    # Next frame paints a single element — its sequence starts back at zero.
    rec.record_element("s", "c", _rect(), 0)
    rec.complete()
    first = rec.snapshot().element_for("s", "c")
    assert first is not None
    assert first.paint_sequence == 0


def test_element_ids_are_scoped_per_scene() -> None:
    rec = GeometryRecorder()
    rec.record_element("a", "submit", _rect(), 0)
    rec.record_element("b", "submit", _rect(x=99.0, y=99.0, w=50.0, h=50.0), 0)
    rec.complete()
    snap = rec.snapshot()
    a = snap.element_for("a", "submit")
    b = snap.element_for("b", "submit")
    assert a is not None
    assert b is not None
    assert a.rect == _rect()
    assert b.rect == _rect(x=99.0, y=99.0, w=50.0, h=50.0)


def test_complete_forgets_the_prior_frame() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "gone", _rect(w=1.0, h=1.0), 0)
    rec.complete()
    # The next frame paints nothing; the element that vanished is absent.
    rec.complete()
    assert rec.snapshot().element_for("s", "gone") is None


def test_to_wire_carries_scene_elements_and_frame_with_z_order() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "title", Rect(x=8.0, y=8.0, width=200.0, height=18.0), 3)
    rec.record_element("other", "hidden", _rect(w=5.0, h=5.0), 4)
    rec.record_frame("f", Rect(x=0.0, y=0.0, width=800.0, height=600.0), 0)
    rec.complete()
    wire = rec.snapshot().to_wire("s", "f")
    assert wire == {
        "elements": {
            "title": {
                "rect": {"x": 8.0, "y": 8.0, "width": 200.0, "height": 18.0},
                "paint_sequence": 0,
                "stack_index": 3,
            }
        },
        "frame": {
            "rect": {"x": 0.0, "y": 0.0, "width": 800.0, "height": 600.0},
            "stack_index": 0,
        },
    }


def test_to_wire_frame_is_null_when_frame_not_painted() -> None:
    rec = GeometryRecorder()
    rec.record_element("s", "title", Rect(x=1.0, y=1.0, width=2.0, height=2.0), 2)
    rec.complete()
    wire = rec.snapshot().to_wire("s", frame_id=None)
    assert wire["frame"] is None
    assert wire["elements"] == {
        "title": {
            "rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0},
            "paint_sequence": 0,
            "stack_index": 2,
        }
    }
