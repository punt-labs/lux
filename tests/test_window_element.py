"""Migration gate for the ABC ``window`` — a display-only composite.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation and the all-ABC fork
gate. A window is deliberately NOT interactive: it carries no close affordance
and declares no remote interaction (ratified Decision 3/c), so there is no
Level-4 dispatch leg — instead the no-close-affordance property is pinned
explicitly so a future "add an X to windows" change must be a deliberate design
decision. Levels 2, 3, and 5 drive the real Hub/Display boundary — the pickle
scene wire and the ``DisplayServer`` receive/rebind path — never a stub.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    LegacyWindowElement,
    ProgressElement,
    TextElement,
    WindowElement,
)
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.elements.window_chrome import WindowFlags, WindowPlacement
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


# -- builders ---------------------------------------------------------------


def _abc_window(
    *,
    title: str = "Panel",
    placement: WindowPlacement | None = None,
    flags: WindowFlags | None = None,
    children: Iterable[AbcElement] | None = None,
) -> WindowElement:
    """Build an all-ABC window holding a text and a button by default."""
    body: tuple[AbcElement, ...] = (
        (TextElement(id="t1", content="left"), ButtonElement(id="b1", label="right"))
        if children is None
        else tuple(children)
    )
    return WindowElement(
        id="w",
        title=title,
        placement=placement or WindowPlacement(x=10, y=20, width=400, height=300),
        flags=flags or WindowFlags(),
        children=body,
    )


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_window_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_window().to_dict())
        assert isinstance(restored, WindowElement)
        assert restored.title == "Panel"
        assert restored.placement == WindowPlacement(x=10, y=20, width=400, height=300)
        assert [c.id for c in restored.children] == ["t1", "b1"]

    def test_flags_roundtrip(self) -> None:
        flags = WindowFlags(no_move=True, no_resize=True, auto_resize=True)
        restored = _decode(_abc_window(flags=flags).to_dict())
        assert isinstance(restored, WindowElement)
        assert restored.flags == flags

    def test_flags_off_are_omitted_from_the_wire(self) -> None:
        wire = _abc_window(flags=WindowFlags(no_move=True)).to_dict()
        assert wire["no_move"] is True
        for off in ("no_resize", "no_collapse", "no_title_bar", "no_scrollbar"):
            assert off not in wire

    def test_default_placement_roundtrips(self) -> None:
        restored = _decode(WindowElement(id="w").to_dict())
        assert isinstance(restored, WindowElement)
        assert restored.placement == WindowPlacement()
        assert restored.children == ()

    def test_abc_children_decode_to_abc(self) -> None:
        restored = _decode(_abc_window().to_dict())
        assert isinstance(restored, WindowElement)
        assert isinstance(restored.children[0], TextElement)
        assert isinstance(restored.children[1], ButtonElement)

    def test_nested_in_abc_group_stays_abc(self) -> None:
        wire = {"kind": "group", "id": "g", "children": [_abc_window().to_dict()]}
        group = _decode(wire)
        assert isinstance(group, HasChildElements)
        window = group.child_elements()[0]
        assert isinstance(window, WindowElement)


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_window_is_abc(self) -> None:
        assert ContainerAbcGate.is_all_abc(_abc_window().to_dict())

    def test_legacy_child_forces_legacy(self) -> None:
        wire = {
            "kind": "window",
            "id": "w",
            "children": [{"kind": "table", "id": "t", "columns": ["A"], "rows": []}],
        }
        assert not ContainerAbcGate.is_all_abc(wire)
        assert isinstance(_decode(wire), LegacyWindowElement)

    def test_from_dict_rejects_non_abc_subtree(self) -> None:
        wire = {
            "kind": "window",
            "id": "w",
            "children": [{"kind": "table", "id": "t", "columns": ["A"], "rows": []}],
        }
        with pytest.raises(ValueError, match="table"):
            WindowElement.from_dict(wire)

    def test_window_in_legacy_container_is_forced_legacy(self) -> None:
        # A window nested inside a legacy tab_bar (a legacy sibling table forces
        # the bar legacy) must itself decode legacy — an ABC container never nests
        # inside a legacy render subtree.
        wire = {
            "kind": "tab_bar",
            "id": "tb",
            "tabs": [
                {
                    "label": "One",
                    "children": [
                        {"kind": "table", "id": "t", "columns": ["A"], "rows": []},
                        _abc_window().to_dict(),
                    ],
                }
            ],
        }
        bar = _decode(wire)
        assert isinstance(bar, HasChildElements)
        window = bar.child_elements()[1]
        assert isinstance(window, LegacyWindowElement)


# -- the deliberate absence of a close affordance ---------------------------


class TestNoCloseAffordance:
    def test_window_declares_no_remote_interaction(self) -> None:
        # A window carries no close/dismiss interaction — it declares no
        # RemoteDispatchSpec, so wrap_handlers_for_remote finds nothing on the
        # window itself to route to the Hub. Forcing this change through a
        # deliberate design decision is the whole point of the assertion.
        window = _abc_window()
        assert window._remote_dispatch_specs() == ()

    def test_wrapping_a_window_sends_nothing_for_the_window_itself(self) -> None:
        # A childless window wrapped for remote dispatch has no bucket to send;
        # a close gesture has nowhere to go because the window emits no event.
        window = WindowElement(id="w")
        sent: list[RemoteEventHandlerInvocation] = []
        window.wrap_handlers_for_remote(sent.append)
        assert sent == []
        assert window.handler_summary() == {}


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_window_has_no_errors(self) -> None:
        assert ElementTreeValidator().validate_tree([_abc_window()]).ok

    def test_non_positive_size_is_reported(self) -> None:
        window = WindowElement(id="w", placement=WindowPlacement(width=0, height=100))
        report = ElementTreeValidator().validate_tree([window])
        assert not report.ok
        assert report.errors[0].element_id == "w"
        assert report.errors[0].element_kind == "window"
        assert "positive width/height" in report.errors[0].message

    @pytest.mark.parametrize("bad", [math.inf, math.nan])
    def test_non_finite_size_is_reported(self, bad: float) -> None:
        # ``inf > 0`` passes a naive positivity test — the spinner-radius defect
        # class. A non-finite extent must be caught before it reaches ImGui.
        window = WindowElement(id="w", placement=WindowPlacement(width=bad, height=100))
        report = ElementTreeValidator().validate_tree([window])
        assert not report.ok
        assert report.errors[0].element_id == "w"
        assert "finite" in report.errors[0].message

    @pytest.mark.parametrize(
        "placement",
        [
            WindowPlacement(x=math.inf, y=20, width=400, height=300),
            WindowPlacement(x=math.nan, y=20, width=400, height=300),
            WindowPlacement(x=10, y=math.inf, width=400, height=300),
            WindowPlacement(x=10, y=math.nan, width=400, height=300),
        ],
    )
    def test_non_finite_position_is_reported(self, placement: WindowPlacement) -> None:
        # x/y were never range-checked before; a non-finite coordinate reaches
        # ImGui's window placement unchecked without this guard.
        report = ElementTreeValidator().validate_tree(
            [WindowElement(id="w", placement=placement)]
        )
        assert not report.ok
        assert report.errors[0].element_id == "w"
        assert "finite" in report.errors[0].message

    def test_offscreen_finite_position_is_allowed(self) -> None:
        # A finite but off-screen position stays unclamped by design — the batch
        # adds no Hub-side clamping semantics.
        placement = WindowPlacement(x=-9000, y=-9000, width=400, height=300)
        assert (
            ElementTreeValidator()
            .validate_tree([WindowElement(id="w", placement=placement)])
            .ok
        )

    def test_nested_malformed_child_is_collected_by_the_walk(self) -> None:
        window = _abc_window(children=(ProgressElement(id="p", fraction=5.0),))
        report = ElementTreeValidator().validate_tree([window])
        assert not report.ok
        assert any(e.element_id == "p" for e in report.errors)

    def test_child_elements_bridges_the_walk(self) -> None:
        window = _abc_window()
        assert window.child_elements() == window.children

    def test_structural_guard_window_is_a_container(self) -> None:
        window = WindowElement(id="w")
        assert isinstance(window, HasChildElements)
        assert isinstance(window, AbcElement)


class TestShowRejectsInvalidWindow:
    @patch(_CLIENT_GET)
    def test_show_rejects_non_positive_size(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [{"kind": "window", "id": "w", "width": 0, "height": 100, "children": []}],
        )
        assert result.startswith("error: scene not rendered")
        assert "[window 'w']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_progress_nested_in_window(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "window",
                    "id": "w",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "progress", "id": "bad", "fraction": -0.5},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[progress 'bad']" in result
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_window_crosses_as_pickled_entry_with_chrome(self) -> None:
        window = _decode(_abc_window(flags=WindowFlags(no_move=True)).to_dict())
        assert isinstance(window, WindowElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[window], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC window must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_window = restored.elements[0]
        assert isinstance(r_window, WindowElement)
        assert r_window.placement == WindowPlacement(x=10, y=20, width=400, height=300)
        assert r_window.flags.no_move is True
        assert [c.id for c in r_window.children] == ["t1", "b1"]


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


def _received(msg: SceneMessage) -> SceneMessage:
    restored = message_from_dict(message_to_dict(msg))
    assert isinstance(restored, SceneMessage)
    return restored


class TestLevel3Crossing:
    def test_rebind_recurses_into_window_children(self) -> None:
        window = _decode(_abc_window().to_dict())
        assert isinstance(window, WindowElement)
        received = _received(SceneMessage(id="s1", elements=[window], frame_id="s1"))
        r_window = received.elements[0]
        assert isinstance(r_window, WindowElement)
        child = r_window.children[0]

        window_factory = r_window._renderer_factory
        child_factory = child._renderer_factory
        assert isinstance(window_factory, RaisingRendererFactory)
        assert isinstance(child_factory, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert r_window._renderer_factory is factory
        assert child._renderer_factory is factory


# -- Level 5: introspection (render_path + resolved props) ------------------


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


class TestLevel5Introspection:
    def test_window_and_children_report_abc_render_path(self) -> None:
        window = _decode(_abc_window().to_dict())
        assert isinstance(window, WindowElement)
        resp = _inspect(_server(), window)
        assert _record(resp, "w")["render_path"] == "abc"
        assert _record(resp, "t1")["render_path"] == "abc"
        assert _record(resp, "b1")["render_path"] == "abc"

    def test_resolved_props_reports_chrome_and_children(self) -> None:
        window = _decode(_abc_window(flags=WindowFlags(no_move=True)).to_dict())
        assert isinstance(window, WindowElement)
        resp = _inspect(_server(), window)
        props = _record(resp, "w")["props"]
        assert isinstance(props, dict)
        assert props["title"] == "Panel"
        assert props["x"] == 10
        assert props["width"] == 400
        assert props["flags"] == ["no_move"]
        assert props["children"] == ["t1", "b1"]

    def test_legacy_window_reports_legacy_render_path(self) -> None:
        legacy = LegacyWindowElement(
            id="w", title="W", children=[TextElement(id="t1", content="x")]
        )
        resp = _inspect(_server(), legacy)
        assert _record(resp, "w")["render_path"] == "legacy"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_window_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(
            _abc_window(flags=WindowFlags(no_move=True))
        )
        assert encoded["kind"] == "window"
        assert encoded["no_move"] is True
        children = cast("list[dict[str, Any]]", encoded["children"])
        assert [child["id"] for child in children] == ["t1", "b1"]


class TestCodecChildrenShape:
    def test_present_non_list_children_raises(self) -> None:
        # A present ``children`` that is not a list is a malformed wire tree; the
        # decoder fails loud (mirrors the modal codec) rather than silently
        # rendering an empty window. Absent children still default to empty.
        wire = {"kind": "window", "id": "w", "children": "oops"}
        with pytest.raises(TypeError, match="window children must be a list"):
            WindowElement.from_dict(wire)

    def test_absent_children_defaults_to_empty(self) -> None:
        restored = WindowElement.from_dict({"kind": "window", "id": "w"})
        assert restored.children == ()


class TestTooltipRoundTrip:
    def test_tooltip_round_trips_through_abc_path(self) -> None:
        window = WindowElement(
            id="w", children=(TextElement(id="t1", content="x"),), tooltip="hint"
        )
        restored = _decode(window.to_dict())
        assert isinstance(restored, WindowElement)
        assert restored.tooltip == "hint"

    def test_absent_tooltip_stays_absent(self) -> None:
        wire = _abc_window().to_dict()
        assert "tooltip" not in wire
        restored = _decode(wire)
        assert isinstance(restored, WindowElement)
        assert restored.tooltip is None
