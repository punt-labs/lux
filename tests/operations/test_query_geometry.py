"""QueryOperations geometry leg + ``GeometryPresent`` wire decode.

``inspect_scene(want_geometry=True)`` proxies the display's painted rects and
narrows them into a discriminated ``SceneGeometry``: present when the reply
carries a usable block, unavailable when the display faults or omits it, and not
requested by default. The rects are display-local truth, read here, never Hub
state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.models.inspect_scope import InspectScope
from punt_lux.operations.models.query_geometry import (
    GeometryNotRequested,
    GeometryPresent,
    GeometryUnavailable,
)
from punt_lux.operations.models.query_inspection import SceneInspection
from punt_lux.operations.queries import QueryOperations
from punt_lux.protocol.geometry import Rect
from punt_lux.protocol.painted_geometry import ElementGeometry, FrameGeometry


class _StubPort:
    """A DisplayPort returning a preset reply for the proxied geometry read."""

    _reply: DisplayReply

    def __new__(cls, reply: DisplayReply) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        return self._reply

    def ping(self, wait: float | None) -> DisplayReply:
        return self._reply


def _seed(store: HubDisplay) -> None:
    text = agent_element_factory().element_from_dict(
        {"kind": "text", "id": "t1", "content": "hi"}
    )
    store.show_scene(
        ConnectionId("c1"),
        SceneId("s1"),
        [cast("DomainElement", text)],
        ScenePresentation(frame_id="f1", frame_title="F1", layout="single"),
    )


_GEOMETRY_BLOCK = {
    "geometry": {
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
}


def test_geometry_not_requested_by_default() -> None:
    store = HubDisplay()
    _seed(store)
    ops = QueryOperations(store, Hub(), _StubPort(DisplayReplied({})))
    result = ops.inspect_scene("s1")
    assert isinstance(result, SceneInspection)
    assert isinstance(result.geometry, GeometryNotRequested)


def test_geometry_present_carries_element_and_frame_rects() -> None:
    store = HubDisplay()
    _seed(store)
    ops = QueryOperations(store, Hub(), _StubPort(DisplayReplied(_GEOMETRY_BLOCK)))
    result = ops.inspect_scene("s1", InspectScope(want_geometry=True))
    assert isinstance(result, SceneInspection)
    assert result.geometry == GeometryPresent(
        frame=FrameGeometry(
            rect=Rect(x=0.0, y=0.0, width=640.0, height=480.0), stack_index=0
        ),
        elements={
            "t1": ElementGeometry(
                rect=Rect(x=8.0, y=8.0, width=120.0, height=18.0),
                paint_sequence=0,
                stack_index=2,
            )
        },
    )


def test_geometry_unavailable_when_display_faults() -> None:
    store = HubDisplay()
    _seed(store)
    ops = QueryOperations(
        store, Hub(), _StubPort(DisplayFault(code="display_unavailable"))
    )
    result = ops.inspect_scene("s1", InspectScope(want_geometry=True))
    assert isinstance(result, SceneInspection)
    assert isinstance(result.geometry, GeometryUnavailable)


def test_geometry_unavailable_when_reply_omits_block() -> None:
    store = HubDisplay()
    _seed(store)
    ops = QueryOperations(store, Hub(), _StubPort(DisplayReplied({"scene_id": "s1"})))
    result = ops.inspect_scene("s1", InspectScope(want_geometry=True))
    assert isinstance(result, SceneInspection)
    assert result.geometry == GeometryUnavailable(
        reason="display reply omitted geometry"
    )


def test_geometry_unavailable_when_a_rect_is_malformed() -> None:
    store = HubDisplay()
    _seed(store)
    bad = {"geometry": {"elements": {"t1": {"x": "wide"}}, "frame": None}}
    ops = QueryOperations(store, Hub(), _StubPort(DisplayReplied(bad)))
    result = ops.inspect_scene("s1", InspectScope(want_geometry=True))
    assert isinstance(result, SceneInspection)
    assert isinstance(result.geometry, GeometryUnavailable)


def test_present_from_block_absent_frame_is_none() -> None:
    present = GeometryPresent.from_block({"elements": {}, "frame": None})
    assert present.frame is None
    assert present.elements == {}


def test_present_from_block_rejects_non_mapping_elements() -> None:
    with pytest.raises(ValueError, match="'elements' must be a mapping"):
        GeometryPresent.from_block({"elements": [], "frame": None})
