"""Migration gate for the ABC ``draw`` leaf — Levels 1-5 + command validation.

A display-only leaf: a 2D canvas whose ``commands`` are a typed ``DrawCommand``
value family, no child elements and no interaction (Level 4 is N/A). Command
well-formedness is a wire-boundary concern (``DrawCommandDecoder.decode_all``
raises on a non-mapping entry, a missing ``cmd``, an unknown kind, or a bad
coordinate), the same composition ruling the tree and plot families follow, so
an invalid canvas is refused before it reaches the display — proven by a
``show()`` rejection of the wrong-schema payload that used to render silently.
Levels 3 and 5 drive the real Hub/Display boundary, never a stub. The
painted-rect test proves the leaf adapter records geometry through the
``measuring`` group.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display import geometry_capture
from punt_lux.display.render_loop import RenderLoop
from punt_lux.display.renderers.imgui.draw import ImGuiDrawRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.agent_factory import agent_element_factory
from punt_lux.protocol.elements import DrawElement, GroupElement
from punt_lux.protocol.elements.draw_commands_line import Line
from punt_lux.protocol.elements.draw_commands_shape import Rect
from punt_lux.protocol.elements.draw_values import Color, Point2
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

from .geometry_doubles import EXPECTED_RECT, FakeGeomImgui, GeomFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


# -- helpers ----------------------------------------------------------------


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> RenderLoop:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return RenderLoop(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _inspect(server: RenderLoop, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_router.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _line() -> Line:
    return Line(p1=Point2(0.0, 0.0), p2=Point2(1.0, 1.0))


def _draw() -> DrawElement:
    return DrawElement(
        id="dr1",
        width=200,
        height=100,
        bg_color="#000000",
        commands=(
            Line(p1=Point2(0.0, 0.0), p2=Point2(10.0, 10.0)),
            Rect(
                min=Point2(10.0, 10.0),
                max=Point2(50.0, 50.0),
                color=Color("#FF0000"),
            ),
        ),
    )


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_draw_roundtrips_to_abc(self) -> None:
        restored = _decode(_draw().to_dict())
        assert isinstance(restored, DrawElement)
        assert restored.width == 200
        assert restored.height == 100
        assert restored.bg_color == "#000000"
        assert len(restored.commands) == 2
        assert isinstance(restored.commands[0], Line)
        assert isinstance(restored.commands[1], Rect)

    def test_defaults(self) -> None:
        draw = DrawElement(id="dr1")
        assert (draw.width, draw.height) == (400, 300)
        assert draw.bg_color is None
        assert draw.commands == ()

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        wire = DrawElement(id="dr1", tooltip="hover").to_dict()
        assert wire["tooltip"] == "hover"
        restored = _decode(wire)
        assert isinstance(restored, DrawElement)
        assert restored.tooltip == "hover"

    def test_bg_color_omitted_when_none(self) -> None:
        wire = DrawElement(id="dr1").to_dict()
        assert "bg_color" not in wire
        assert wire["commands"] == []


# -- command validation: reject a malformed command at the Hub --------------


class TestCommandValidationAtHub:
    def test_missing_cmd_field_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="missing or invalid 'cmd'"):
            DrawElement.from_dict(
                {
                    "kind": "draw",
                    "id": "dr1",
                    "commands": [{"op": "circle", "x": 100, "y": 100, "r": 40}],
                }
            )

    def test_unknown_cmd_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="unknown 'cmd'"):
            DrawElement.from_dict(
                {"kind": "draw", "id": "dr1", "commands": [{"cmd": "blob"}]}
            )

    def test_non_list_commands_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="commands must be a list"):
            DrawElement.from_dict({"kind": "draw", "id": "dr1", "commands": 5})

    def test_non_mapping_command_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"commands\[0\] must be a mapping"):
            DrawElement.from_dict(
                {"kind": "draw", "id": "dr1", "commands": ["not-a-dict"]}
            )

    def test_valid_draw_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([_draw()]).ok

    @patch(_CLIENT_GET)
    def test_show_rejects_the_wrong_schema_command(self, mock_get: MagicMock) -> None:
        """The wrong-schema command that used to render silently is refused."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "draw",
                    "id": "dr1",
                    "commands": [{"op": "circle", "x": 100, "y": 100, "r": 40}],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "cmd" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_malformed_command_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [
                        {"kind": "draw", "id": "dr1", "commands": [{"cmd": "blob"}]}
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_draw_crosses_as_pickled_entry(self) -> None:
        wire = message_to_dict(SceneMessage(id="s1", elements=[_draw()], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC draw must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, DrawElement)
        assert len(r.commands) == 2
        assert isinstance(r.commands[1], Rect)


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_draw_renderer_factory(self) -> None:
        received = message_from_dict(
            message_to_dict(SceneMessage(id="s1", elements=[_draw()], frame_id="s1"))
        )
        assert isinstance(received, SceneMessage)
        draw = received.elements[0]
        assert isinstance(draw, DrawElement)
        before = draw._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert draw._renderer_factory is factory


# -- ABC decode nesting -----------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_draw_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "draw", "id": "dr1"}],
        }
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], DrawElement)


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_draw_is_recorded(self) -> None:
        resp = _inspect(_server(), _draw())
        assert _record(resp, "dr1")["kind"] == "draw"

    def test_draw_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), DrawElement(id="dr1", width=200))
        props = _record(resp, "dr1")["props"]
        assert props == {
            "width": 200,
            "height": 300,
            "bg_color": None,
            "commands": [],
            "tooltip": None,
        }


class TestPatchPath:
    def test_apply_patch_replaces_commands_in_place(self) -> None:
        draw = DrawElement(id="dr1", commands=(_line(),))
        returned = draw.apply_patch(
            {"commands": [{"cmd": "line", "p1": [0, 0], "p2": [5, 5]}]}
        )
        assert returned is draw
        assert len(draw.commands) == 1
        assert isinstance(draw.commands[0], Line)

    def test_apply_patch_sets_size_and_bg(self) -> None:
        draw = DrawElement(id="dr1")
        draw.apply_patch({"width": 640, "height": 480, "bg_color": "#101010"})
        assert (draw.width, draw.height, draw.bg_color) == (640, 480, "#101010")

    def test_apply_patch_rejects_malformed_command(self) -> None:
        draw = DrawElement(id="dr1", commands=(_line(),))
        with pytest.raises(ValueError, match="unknown 'cmd'"):
            draw.apply_patch({"commands": [{"cmd": "blob"}]})
        assert len(draw.commands) == 1


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_draw_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(_draw())
        assert encoded["kind"] == "draw"
        assert encoded["width"] == 200
        assert isinstance(encoded["commands"], list)
        assert len(encoded["commands"]) == 2


# -- painted geometry: the leaf records a rect through the measuring group ---


def _draw_paint_imgui() -> MagicMock:
    """A painting-imgui mock whose cursor read carries real float coordinates.

    ``DrawElementRenderer`` builds ``ImVec2`` from the cursor position, so the
    mock must return numeric ``.x``/``.y`` — the recorded rect still comes from
    the geometry double, not from this painting pass.
    """
    imgui = MagicMock()
    pos = MagicMock()
    pos.x = 0.0
    pos.y = 0.0
    imgui.get_cursor_screen_pos.return_value = pos
    return imgui


def test_draw_adapter_records_a_painted_rect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geometry_capture, "imgui", FakeGeomImgui())
    monkeypatch.setattr(
        "punt_lux.display.renderers.draw_element_renderer.imgui", _draw_paint_imgui()
    )
    factory = GeomFactory()
    factory.geometry.enter_scene("s1")

    adapter = ImGuiDrawRenderer(_draw(), cast("ImGuiRendererFactory", factory))
    adapter.paint()
    factory.geometry.complete()

    geom = factory.geometry.recorder.snapshot().element_for("s1", "dr1")
    assert geom is not None
    assert geom.rect == EXPECTED_RECT
