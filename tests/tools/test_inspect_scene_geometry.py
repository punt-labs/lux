"""The MCP ``inspect_scene`` tool carries painted geometry when asked.

Drives the real ``inspect_scene`` tool with ``want_geometry=True`` over a seeded
Hub store and a stub display client that returns a geometry block, so the whole
tool → operations → display-proxy → decode path is exercised and the Z-order wire
shape is locked at the MCP surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.models.query_geometry import GeometryPresent
from punt_lux.operations.models.query_inspection import SceneInspection
from punt_lux.operations.ports import HubPorts
from punt_lux.protocol.agent_factory import agent_element_factory
from punt_lux.protocol.geometry import Rect
from punt_lux.protocol.painted_geometry import ElementGeometry, FrameGeometry
from punt_lux.tools import read_tools

if TYPE_CHECKING:
    import pytest

_GEOMETRY_REPLY: dict[str, object] = {
    "scene_id": "s1",
    "geometry": {
        "elements": {
            "t1": {
                "rect": {"x": 8.0, "y": 8.0, "width": 120.0, "height": 18.0},
                "paint_sequence": 0,
                "stack_index": 2,
            }
        },
        "anonymous": {
            "separator:1": {
                "rect": {"x": 0.0, "y": 30.0, "width": 100.0, "height": 1.0},
                "paint_sequence": 1,
                "stack_index": 2,
            }
        },
        "frame": {
            "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
            "stack_index": 0,
        },
    },
}


class _Reply:
    """A display query response: no error, the geometry reply as its result."""

    error: None
    result: dict[str, object]
    __slots__ = ("error", "result")

    def __new__(cls, result: dict[str, object]) -> Self:
        self = super().__new__(cls)
        self.error = None
        self.result = result
        return self


class _StubClient:
    """A display client whose ``query`` returns the seeded geometry reply."""

    __slots__ = ()

    def query(self, method: str, params: dict[str, object]) -> _Reply:
        return _Reply(_GEOMETRY_REPLY)


class _NullReplicator:
    """A ``DirtyMarker`` that ignores every push — the tool test never renders."""

    __slots__ = ()

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Ignore the dirty mark — no display to replicate to."""

    def mark_menus(self) -> None:
        """Ignore the menu mark — no display to replicate to."""


def _seed(store: HubDisplay) -> None:
    # Seeded under "local" — the default MCP session key (tools/server.py) —
    # so the tool's own caller-scoped composition finds it (DES-086).
    text = agent_element_factory().element_from_dict(
        {"kind": "text", "id": "t1", "content": "hi"}
    )
    store.show_scene(
        ConnectionId("local"),
        SceneId(ConnectionScopedId.compose(ConnectionId("local"), "s1")),
        [cast("DomainElement", text)],
        ScenePresentation(frame_id="f1", frame_title="F1", layout="single"),
    )


def test_inspect_scene_tool_carries_z_order_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HubDisplay()
    _seed(store)
    ops = Operations.for_store(
        store,
        _NullReplicator(),
        hub=hub,
        client_registry=client_registry,
        menu_registry=HubMenuRegistry(),
        callback_router=CallbackRouter(store.clients),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=ensure_writer,
            next_event=next_event,
            display_port=HubDisplayConnection(
                is_running=lambda: True, clients=client_registry
            ),
        ),
    )
    monkeypatch.setattr("punt_lux.tools.tools.OPERATIONS", ops)
    monkeypatch.setattr("punt_lux.domain.hub.clients.client_registry.get", _StubClient)

    result = read_tools.inspect_scene("s1", want_geometry=True)

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
        anonymous={
            "separator:1": ElementGeometry(
                rect=Rect(x=0.0, y=30.0, width=100.0, height=1.0),
                paint_sequence=1,
                stack_index=2,
            )
        },
    )
