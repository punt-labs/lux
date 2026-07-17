"""Migration gate for the ABC ``radio`` — an atomic-selection interactive input.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, the wire-boundary rejection, and the capability guard. The
interactive value flows as an ``int`` selection index on ``ValueChanged`` — the
checkbox pattern with an integer payload, no ``ContinuousEditArbiter``.
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
from punt_lux.protocol.elements import RadioElement, build_element_codec
from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_kind_verify import AbcKindVerifier
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry
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
        elem = RadioElement(id="ra", label="Pick", items=["A", "B", "C"], selected=1)
        restored = _decode(elem.to_dict())
        assert isinstance(restored, RadioElement)
        assert restored.selected == 1
        assert restored.items == ["A", "B", "C"]
        assert restored.label == "Pick"

    def test_tooltipless_wire_is_byte_identical_to_legacy(self) -> None:
        # The legacy dataclass emitted exactly these five keys; a tooltip-less
        # radio must match byte-for-byte so snapshot parity holds.
        payload = RadioElement(id="ra", label="Pick", items=["A", "B"]).to_dict()
        assert payload == {
            "kind": "radio",
            "id": "ra",
            "label": "Pick",
            "items": ["A", "B"],
            "selected": 0,
        }

    def test_tooltip_round_trips(self) -> None:
        # The legacy to_dict silently dropped tooltip; the ABC encoder keeps it.
        elem = RadioElement(id="ra", items=["A"], tooltip="choose one")
        payload = elem.to_dict()
        assert payload["tooltip"] == "choose one"
        restored = _decode(payload)
        assert isinstance(restored, RadioElement)
        assert restored.tooltip == "choose one"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(RadioElement(id="ra", items=["A"]).to_dict())
        assert isinstance(restored, RadioElement)
        assert restored.tooltip is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(RadioElement(id="ra", items=["A", "B"]))
        assert encoded["kind"] == "radio"
        assert encoded["selected"] == 0

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``spinner``) stays the negative control.
        kinds = build_element_codec().registered_kinds
        assert "radio" not in kinds
        assert "spinner" in kinds


# -- capability guard: radio cannot ship handler-less -----------------------


class TestCapabilityGuard:
    def test_radio_is_a_registered_interactive_kind(self) -> None:
        assert "radio" in AbcKindNames.MIGRATED_ABC_KINDS
        assert "radio" in AbcKindVerifier.INTERACTIVE_KINDS

    def test_guard_rejects_a_handler_less_radio_spec(self) -> None:
        from punt_lux.protocol.elements.abc_kind_codec import KindCodec
        from punt_lux.protocol.elements.abc_leaf_spec import LeafKindSpec
        from punt_lux.protocol.elements.radio_codec import (
            JsonRadioDecoder,
            JsonRadioEncoder,
        )

        registry = AbcElementRegistry()
        # A spec that forgets its handler_builder must fail the capability check.
        registry.register(
            LeafKindSpec(
                kind="radio",
                codec=KindCodec(
                    RadioElement, JsonRadioDecoder, JsonRadioEncoder().encode
                ),
            )
        )
        with pytest.raises(RuntimeError, match="handlers"):
            AbcKindVerifier._verify_capabilities(registry)


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"radio element.*'id'"):
            RadioElement.from_dict({"label": "N", "items": ["A"]})

    def test_non_string_item_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"radio element.*items"):
            RadioElement.from_dict({"id": "ra", "items": ["A", 3]})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            RadioElement.from_dict(
                {"id": "ra", "items": ["A"], "handlers": {"not": "a list"}}
            )


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_radio_has_no_errors(self) -> None:
        assert RadioElement(id="ra", items=["A", "B"], selected=1).validate() == ()

    def test_is_an_abc_element(self) -> None:
        assert isinstance(RadioElement(id="ra"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert RadioElement(id="ra").child_elements() == ()

    def test_negative_index_reports_one_error(self) -> None:
        errors = RadioElement(id="ra", items=["A"], selected=-1).validate()
        assert len(errors) == 1
        assert ">= 0" in errors[0].message
        assert errors[0].element_kind == "radio"

    def test_out_of_range_index_reports_one_error(self) -> None:
        errors = RadioElement(id="ra", items=["A", "B"], selected=5).validate()
        assert len(errors) == 1
        assert "selected" in errors[0].message
        assert "len(items)" in errors[0].message

    def test_itemless_nonzero_index_reports_one_error(self) -> None:
        errors = RadioElement(id="ra", items=[], selected=2).validate()
        assert len(errors) == 1
        assert "empty" in errors[0].message

    def test_itemless_zero_index_is_valid(self) -> None:
        # A radio group awaiting deferred population is valid at index 0.
        assert RadioElement(id="ra", items=[], selected=0).validate() == ()

    def test_valid_radio_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([RadioElement(id="ra")]).ok


class TestShowRejectsInvalidRadio:
    @patch(_CLIENT_GET)
    def test_show_rejects_out_of_range_index(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1", [{"kind": "radio", "id": "ra", "items": ["A", "B"], "selected": 9}]
        )
        assert result.startswith("error: scene not rendered")
        assert "[radio 'ra']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_radio_nested_in_group(self, mock_get: MagicMock) -> None:
        """A bad radio nested in an all-ABC group is collected by the walk."""
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
                        {"kind": "radio", "id": "bad", "items": ["A"], "selected": 3},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[radio 'bad']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_radio_nested_in_collapsing_header(
        self, mock_get: MagicMock
    ) -> None:
        """A bad radio nested in a collapsing_header is collected by the walk."""
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
                        {"kind": "radio", "id": "bad", "items": ["A"], "selected": 3},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[radio 'bad']" in result
        client.show.assert_not_called()


# -- patch path (validate the index at the boundary, not per setter) --------


class TestPatchPath:
    def test_apply_patch_advances_selected_in_place(self) -> None:
        r = RadioElement(id="ra", items=["A", "B", "C"], selected=0)
        returned = r.apply_patch({"selected": 2})
        assert returned is r
        assert r.selected == 2

    def test_combined_items_then_index_is_judged_on_final_state(self) -> None:
        # ``selected`` 3 exceeds the current 2-item list, but the same patch
        # widens ``items`` to 4. A per-setter raise would wrongly reject; the
        # element-boundary re-check judges the final state and accepts it.
        r = RadioElement(id="ra", items=["A", "B"], selected=0)
        r.apply_patch({"items": ["A", "B", "C", "D"], "selected": 3})
        assert r.selected == 3
        assert r.items == ["A", "B", "C", "D"]

    def test_apply_patch_rejects_out_of_range_and_rolls_back(self) -> None:
        r = RadioElement(id="ra", items=["A", "B"], selected=1)
        with pytest.raises(ValueError, match="selected"):
            r.apply_patch({"selected": 9})
        assert r.selected == 1

    def test_apply_patch_rejects_non_int_index(self) -> None:
        r = RadioElement(id="ra", items=["A", "B"], selected=0)
        with pytest.raises(TypeError, match="selected"):
            r.apply_patch({"selected": "one"})
        assert r.selected == 0

    def test_apply_patch_rejects_bool_index(self) -> None:
        # ``bool`` is a subclass of ``int`` but is never a valid selection index.
        r = RadioElement(id="ra", items=["A", "B"], selected=0)
        with pytest.raises(TypeError, match="selected"):
            r.apply_patch({"selected": True})
        assert r.selected == 0

    def test_apply_patch_is_atomic_on_range_rejection(self) -> None:
        r = RadioElement(id="ra", items=["A", "B"], selected=0, label="orig")
        with pytest.raises(ValueError, match="selected"):
            r.apply_patch({"label": "new", "selected": 9})
        assert r.label == "orig"
        assert r.selected == 0


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_radio_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "radio", "id": "ra", "items": ["A"]}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(RadioElement(id="ra", items=["A", "B"], selected=1).to_dict())
        assert isinstance(elem, RadioElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC radio must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, RadioElement)
        assert r_elem.selected == 1

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(RadioElement(id="ra", items=["A"]).to_dict())
        assert isinstance(elem, RadioElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, RadioElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_radio_renderer_factory(self) -> None:
        scene = SceneMessage(
            id="s1", elements=[RadioElement(id="ra", items=["A"], selected=0)]
        )
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        radio = received.elements[0]
        assert isinstance(radio, RadioElement)

        before = radio._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert radio._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_selection_on_the_hub_copy(self) -> None:
        elem = _decode(RadioElement(id="ra", items=["A", "B", "C"]).to_dict())
        assert isinstance(elem, RadioElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("ra"),
                owner_id=ClientId("c"),
                value=2,
            )
        )
        assert elem.selected == 2

    def test_hub_driven_change_does_not_refire(self) -> None:
        # A Hub-set index must NOT emit a RemoteEventHandlerInvocation; a genuine
        # pick DOES emit exactly one, carrying the int index.
        elem = _decode(RadioElement(id="ra", items=["A", "B", "C"]).to_dict())
        assert isinstance(elem, RadioElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"selected": 1})
        assert sent == [], "a Hub-set index must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("ra"),
                owner_id=ClientId("c"),
                value=2,
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "value_changed"
        assert sent[0].value == 2


# -- Level 5: introspection (render_path + resolved props) ------------------


class TestLevel5Introspection:
    def test_reports_abc_render_path(self) -> None:
        elem = _decode(RadioElement(id="ra", items=["A"], selected=0).to_dict())
        record = _record(_inspect(_server(), elem), "ra")
        assert record["render_path"] == "abc"

    def test_resolved_props_read_back_including_defaults(self) -> None:
        elem = _decode(
            RadioElement(id="ra", label="Pick", items=["A", "B"], selected=1).to_dict()
        )
        props = _record(_inspect(_server(), elem), "ra")["props"]
        assert isinstance(props, dict)
        assert props == {
            "label": "Pick",
            "items": ["A", "B"],
            "selected": 1,
            "tooltip": None,
        }
