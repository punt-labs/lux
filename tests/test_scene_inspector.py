"""Unit tests for ``SceneInspector`` — the enriched inspect_scene handler.

The integration path (through a real ``DisplayServer``) lives in
``test_scene_inspection.py``. These isolate the collaborator: a real
``SceneManager`` supplies the element objects, a real (empty) domain
``Display`` supplies mirror presence, and a ``GeometryRecorder`` supplies the
painted rects the ``want_geometry`` reply carries.
"""

from __future__ import annotations

import pytest

from punt_lux.display.geometry import GeometryRecorder
from punt_lux.domain.display import Display
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import TextElement
from punt_lux.protocol.geometry import Rect
from punt_lux.scene import SceneManager
from punt_lux.scene_inspector import SceneInspector


def _scene_manager_with(scene: SceneMessage) -> SceneManager:
    sm = SceneManager(on_scene_replaced=lambda _ids: None)
    sm.handle_framed_scene(scene, owner_fd=0)
    return sm


def _inspector(
    sm: SceneManager, geometry: GeometryRecorder | None = None
) -> SceneInspector:
    return SceneInspector(
        scene_manager=sm,
        domain_display=Display(),
        geometry=geometry if geometry is not None else GeometryRecorder(),
    )


def test_inspect_reads_element_types_and_empty_mirror() -> None:
    sm = _scene_manager_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    result = _inspector(sm).inspect("s1")
    rec = result["element_paths"][0]
    assert rec["render_path"] == "abc"
    # an empty domain Display mirror means the element is not (yet) present
    assert rec["domain_mirror_present"] is False


def test_inspect_missing_scene_raises_lookup_error() -> None:
    with pytest.raises(LookupError, match="ghost"):
        _inspector(SceneManager(on_scene_replaced=lambda _ids: None)).inspect("ghost")


def test_inspect_omits_geometry_unless_requested() -> None:
    sm = _scene_manager_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    assert "geometry" not in _inspector(sm).inspect("s1")


def test_inspect_returns_captured_geometry_when_requested() -> None:
    sm = _scene_manager_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    geometry = GeometryRecorder()
    geometry.record_element("s1", "t1", Rect(x=8.0, y=8.0, width=120.0, height=18.0), 2)
    geometry.record_frame("s1", Rect(x=0.0, y=0.0, width=640.0, height=480.0), 0)
    geometry.complete()

    result = _inspector(sm, geometry).inspect("s1", want_geometry=True)
    assert result["geometry"] == {
        "elements": {
            "t1": {
                "rect": {"x": 8.0, "y": 8.0, "width": 120.0, "height": 18.0},
                "paint_sequence": 0,
                "stack_index": 2,
            }
        },
        "frame": {
            "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
            "stack_index": 0,
        },
    }


def test_unpainted_element_is_absent_from_geometry() -> None:
    sm = _scene_manager_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    # The recorder captured nothing this frame — the element is in the tree but
    # absent from the geometry block, the "not painted" answer.
    result = _inspector(sm).inspect("s1", want_geometry=True)
    assert result["geometry"]["elements"] == {}
    assert result["geometry"]["frame"] is None
