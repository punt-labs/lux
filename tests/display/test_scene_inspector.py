"""Unit tests for ``SceneInspector`` — the enriched inspect_scene handler.

The integration path (through a real ``DisplayServer``) lives in
``test_scene_inspection.py``. These isolate the collaborator: a real
``SceneReplica`` supplies the element objects and a ``GeometryRecorder``
supplies the painted rects the ``want_geometry`` reply carries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

import pytest

from punt_lux.display.geometry import ElementRef, GeometryRecorder
from punt_lux.display.replica import SceneReplica
from punt_lux.display.scene_inspector import SceneInspector
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import TextElement
from punt_lux.protocol.geometry import Rect

if TYPE_CHECKING:
    from collections.abc import Mapping


def _replica_with(scene: SceneMessage) -> SceneReplica:
    sm = SceneReplica(on_scene_replaced=lambda _ids: None)
    sm.handle_framed_scene(scene, owner_fd=0)
    return sm


def _inspector(
    sm: SceneReplica, geometry: GeometryRecorder | None = None
) -> SceneInspector:
    return SceneInspector(
        scenes=sm,
        geometry=geometry if geometry is not None else GeometryRecorder(),
    )


def test_inspect_reads_element_kind() -> None:
    sm = _replica_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    result = _inspector(sm).inspect("s1")
    rec = result["element_paths"][0]
    assert rec["id"] == "t1"
    assert rec["kind"] == "text"


def test_inspect_missing_scene_raises_lookup_error() -> None:
    with pytest.raises(LookupError, match="ghost"):
        _inspector(SceneReplica(on_scene_replaced=lambda _ids: None)).inspect("ghost")


def test_inspect_omits_geometry_unless_requested() -> None:
    sm = _replica_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    assert "geometry" not in _inspector(sm).inspect("s1")


def test_inspect_returns_captured_geometry_when_requested() -> None:
    sm = _replica_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    geometry = GeometryRecorder()
    geometry.record_element(
        "s1", ElementRef("t1", "text"), Rect(x=8.0, y=8.0, width=120.0, height=18.0), 2
    )
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
        "anonymous": {},
        "frame": {
            "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
            "stack_index": 0,
        },
    }


def test_unpainted_element_is_absent_from_geometry() -> None:
    sm = _replica_with(
        SceneMessage(
            id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
        )
    )
    # The recorder captured nothing this frame — the element is in the tree but
    # absent from the geometry block, the "not painted" answer.
    result = _inspector(sm).inspect("s1", want_geometry=True)
    assert result["geometry"]["elements"] == {}
    assert result["geometry"]["frame"] is None


class _UnmappedScenes:
    """A scene manager whose scene resolves but carries no frame mapping.

    The real ``SceneReplica`` cannot produce this — ``resolve_scene`` finds a
    scene *through* ``scene_to_frame`` — so it models the invariant violation the
    indexed frame lookup exists to surface loudly instead of reporting the frame
    as merely not painted.
    """

    _scene: SceneMessage
    __slots__ = ("_scene",)

    def __new__(cls, scene: SceneMessage) -> Self:
        self = super().__new__(cls)
        self._scene = scene
        return self

    def resolve_scene(self, _scene_id: str) -> SceneMessage:
        return self._scene

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        return {}


def test_geometry_raises_when_a_resolved_scene_has_no_frame() -> None:
    scene = SceneMessage(
        id="s1", elements=[TextElement(id="t1", content="hi")], frame_id="s1"
    )
    inspector = SceneInspector(
        scenes=cast("SceneReplica", _UnmappedScenes(scene)),
        geometry=GeometryRecorder(),
    )
    # The missing mapping surfaces as KeyError, which the dispatcher reports as
    # geometry-unavailable — not silently as a not-painted frame.
    with pytest.raises(KeyError):
        inspector.inspect("s1", want_geometry=True)
