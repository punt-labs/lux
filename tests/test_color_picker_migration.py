"""Migration gate for the ABC ``color_picker`` — an interactive color input.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, and the wire-boundary rejection. The interactive value flows as a
hex ``str`` payload on ``ValueChanged`` — the existing ``str`` arm, the one
``input_text`` uses — so no ``ValueChanged`` union widening was needed. The only
protocol change is activating the previously wire-dead ``tooltip``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import ColorPickerElement, build_element_codec
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


def _decode(wire: Mapping[str, object]) -> object:
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _inspect(server: DisplayServer, elem: object) -> QueryResponse:
    sock = MagicMock()
    sock.fileno.return_value = 7
    server._handle_message(sock, SceneMessage(id="s1", elements=[cast("Any", elem)]))
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_roundtrips_to_abc(self) -> None:
        elem = ColorPickerElement(id="cp", label="Bg", value="#1A2B3C")
        restored = _decode(elem.to_dict())
        assert isinstance(restored, ColorPickerElement)
        assert restored.value == "#1A2B3C"
        assert restored.label == "Bg"

    def test_alpha_and_picker_variant_round_trip(self) -> None:
        elem = ColorPickerElement(
            id="cp", label="Fill", value="#FF8080AA", alpha=True, picker=True
        )
        payload = elem.to_dict()
        assert payload["alpha"] is True
        assert payload["picker"] is True
        restored = _decode(payload)
        assert isinstance(restored, ColorPickerElement)
        assert restored.alpha is True
        assert restored.picker is True

    def test_defaults_omitted_on_the_wire(self) -> None:
        payload = ColorPickerElement(id="cp", label="C").to_dict()
        assert "alpha" not in payload
        assert "picker" not in payload
        assert payload == {
            "kind": "color_picker",
            "id": "cp",
            "label": "C",
            "value": "#FFFFFF",
        }

    def test_tooltip_round_trips(self) -> None:
        elem = ColorPickerElement(id="cp", label="C", tooltip="pick a color")
        payload = elem.to_dict()
        assert payload["tooltip"] == "pick a color"
        restored = _decode(payload)
        assert isinstance(restored, ColorPickerElement)
        assert restored.tooltip == "pick a color"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(ColorPickerElement(id="cp", label="C").to_dict())
        assert isinstance(restored, ColorPickerElement)
        assert restored.tooltip is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(ColorPickerElement(id="cp", label="C"))
        assert encoded["kind"] == "color_picker"
        assert encoded["value"] == "#FFFFFF"

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``combo``) stays registered as the negative control.
        kinds = build_element_codec().registered_kinds
        assert "color_picker" not in kinds
        assert "combo" in kinds


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_non_string_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"color_picker element.*'value'"):
            ColorPickerElement.from_dict({"id": "cp", "label": "C", "value": 255})

    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"color_picker element.*'id'"):
            ColorPickerElement.from_dict({"label": "C"})

    def test_non_bool_alpha_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"color_picker element.*'alpha'"):
            ColorPickerElement.from_dict({"id": "cp", "label": "C", "alpha": 1})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            ColorPickerElement.from_dict(
                {"id": "cp", "label": "C", "handlers": {"not": "a list"}}
            )


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_color_picker_has_no_errors(self) -> None:
        assert ColorPickerElement(id="cp", value="#00FF00").validate() == ()

    def test_valid_rgba_hex_has_no_errors(self) -> None:
        elem = ColorPickerElement(id="cp", value="#00FF0080", alpha=True)
        assert elem.validate() == ()

    def test_is_an_abc_element(self) -> None:
        assert isinstance(ColorPickerElement(id="cp"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert ColorPickerElement(id="cp").child_elements() == ()

    @pytest.mark.parametrize(
        "bad", ["FF0000", "#FF00", "#GGGGGG", "#FF00000", "red", "", "#FF00GG"]
    )
    def test_malformed_hex_reports_one_error(self, bad: str) -> None:
        # Missing '#', wrong length (4/7 digits), non-hex digits, and empty all
        # fault: a malformed hex cannot be parsed to a color the reconciliation
        # can compare, so it is rejected before render.
        errors = ColorPickerElement(id="cp", value=bad).validate()
        assert len(errors) == 1
        assert "value" in errors[0].message
        assert errors[0].element_kind == "color_picker"

    def test_rgb_hex_under_alpha_is_lenient(self) -> None:
        # alpha=True with a 6-digit value pads to opaque — accepted, not rejected.
        assert ColorPickerElement(id="cp", value="#112233", alpha=True).validate() == ()

    def test_rgba_hex_under_rgb_is_lenient(self) -> None:
        # alpha=False with an 8-digit value drops its alpha in the encoder —
        # accepted, not rejected (the deliberate check-2 leniency).
        assert ColorPickerElement(id="cp", value="#11223380").validate() == ()

    def test_valid_color_picker_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([ColorPickerElement(id="cp")]).ok


class TestShowRejectsInvalidColorPicker:
    @patch(_CLIENT_GET)
    def test_show_rejects_malformed_hex(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "color_picker", "id": "cp", "value": "red"}])
        assert result.startswith("error: scene not rendered")
        assert "[color_picker 'cp']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_color_picker_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        """A bad picker nested in an all-ABC group is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "color_picker", "id": "bad", "value": "#XYZ"},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[color_picker 'bad']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_color_picker_nested_in_collapsing_header(
        self, mock_get: MagicMock
    ) -> None:
        """A bad picker nested in a collapsing_header is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "collapsing_header",
                    "id": "hdr",
                    "label": "Details",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "color_picker", "id": "bad", "value": "nope"},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[color_picker 'bad']" in result
        client.show.assert_not_called()


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_color_picker_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "color_picker", "id": "cp", "label": "C"}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(ColorPickerElement(id="cp", value="#123456").to_dict())
        assert isinstance(elem, ColorPickerElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC color_picker must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, ColorPickerElement)
        assert r_elem.value == "#123456"

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(ColorPickerElement(id="cp", label="C").to_dict())
        assert isinstance(elem, ColorPickerElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, ColorPickerElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_color_picker_renderer_factory(self) -> None:
        scene = SceneMessage(
            id="s1", elements=[ColorPickerElement(id="cp", value="#FF0000")]
        )
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        picker = received.elements[0]
        assert isinstance(picker, ColorPickerElement)

        before = picker._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert picker._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_value_on_the_hub_copy(self) -> None:
        built = ColorPickerElement(id="cp", label="C", value="#000000")
        elem = _decode(built.to_dict())
        assert isinstance(elem, ColorPickerElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("cp"),
                owner_id=ClientId("c"),
                value="#ABCDEF",
            )
        )
        assert elem.value == "#ABCDEF"

    def test_hub_driven_change_does_not_refire(self) -> None:
        # A Hub-set value must NOT emit a RemoteEventHandlerInvocation; a genuine
        # commit DOES emit exactly one, carrying the hex string.
        elem = _decode(ColorPickerElement(id="cp", label="C").to_dict())
        assert isinstance(elem, ColorPickerElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"value": "#101010"})
        assert sent == [], "a Hub-set value must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("cp"),
                owner_id=ClientId("c"),
                value="#202020",
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "value_changed"
        assert sent[0].value == "#202020"


# -- Level 5: introspection (render_path + resolved props) ------------------


class TestLevel5Introspection:
    def test_reports_abc_render_path(self) -> None:
        elem = _decode(ColorPickerElement(id="cp", value="#FF0000").to_dict())
        record = _record(_inspect(_server(), elem), "cp")
        assert record["render_path"] == "abc"

    def test_resolved_props_read_back_including_defaults(self) -> None:
        elem = _decode(
            ColorPickerElement(
                id="cp", label="Bg", value="#FF8080AA", alpha=True, picker=True
            ).to_dict()
        )
        props = _record(_inspect(_server(), elem), "cp")["props"]
        assert isinstance(props, dict)
        assert props == {
            "value": "#FF8080AA",
            "alpha": True,
            "picker": True,
            "tooltip": None,
        }
