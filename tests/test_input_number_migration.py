"""Migration gate for the ABC ``input_number`` — an interactive numeric input.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, the wire-boundary rejection, and the mutable-bounds patch rule.
The interactive value flows as a ``float`` payload on ``ValueChanged`` (an
``int`` for the integer variant), mirroring the slider migration. The one
field-shape difference from ``slider`` is that ``min`` / ``max`` / ``step`` are
genuinely optional (``None`` = unbounded / no stepper).
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
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import InputNumberElement, build_element_codec
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
        elem = InputNumberElement(
            id="in", label="Price", value=9.99, min=0.0, max=100.0, step=0.01
        )
        restored = _decode(elem.to_dict())
        assert isinstance(restored, InputNumberElement)
        assert restored.value == 9.99
        assert restored.min == 0.0
        assert restored.max == 100.0
        assert restored.step == 0.01

    def test_integer_variant_round_trips(self) -> None:
        elem = InputNumberElement(id="in", label="N", value=5.0, integer=True)
        payload = elem.to_dict()
        assert payload["integer"] is True
        restored = _decode(payload)
        assert isinstance(restored, InputNumberElement)
        assert restored.integer is True

    def test_unbounded_omits_min_max_step_on_the_wire(self) -> None:
        payload = InputNumberElement(id="in", label="N").to_dict()
        assert payload == {
            "kind": "input_number",
            "id": "in",
            "label": "N",
            "value": 0.0,
            "format": "%.3f",
        }

    def test_integer_variant_default_format_is_percent_d(self) -> None:
        elem = InputNumberElement(id="in", label="N", integer=True)
        assert elem.format == "%d"

    def test_tooltip_round_trips(self) -> None:
        elem = InputNumberElement(id="in", label="N", tooltip="type a number")
        payload = elem.to_dict()
        assert payload["tooltip"] == "type a number"
        restored = _decode(payload)
        assert isinstance(restored, InputNumberElement)
        assert restored.tooltip == "type a number"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(InputNumberElement(id="in", label="N").to_dict())
        assert isinstance(restored, InputNumberElement)
        assert restored.tooltip is None

    def test_null_bounds_decode_to_none(self) -> None:
        restored = _decode(
            {"kind": "input_number", "id": "in", "min": None, "max": None, "step": None}
        )
        assert isinstance(restored, InputNumberElement)
        assert restored.min is None
        assert restored.max is None
        assert restored.step is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(InputNumberElement(id="in", label="N"))
        assert encoded["kind"] == "input_number"
        assert encoded["value"] == 0.0

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``selectable``) stays the negative control.
        kinds = build_element_codec().registered_kinds
        assert "input_number" not in kinds
        assert "selectable" in kinds


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_non_numeric_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"input_number element.*'value'"):
            InputNumberElement.from_dict({"id": "in", "label": "N", "value": "ten"})

    def test_non_numeric_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"input_number element.*'step'"):
            InputNumberElement.from_dict({"id": "in", "label": "N", "step": "fast"})

    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"input_number element.*'id'"):
            InputNumberElement.from_dict({"label": "N"})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            InputNumberElement.from_dict(
                {"id": "in", "label": "N", "handlers": {"not": "a list"}}
            )


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_input_has_no_errors(self) -> None:
        elem = InputNumberElement(id="in", value=50.0, min=0.0, max=100.0)
        assert elem.validate() == ()

    def test_unbounded_input_has_no_errors(self) -> None:
        # No bounds at all: every finite value is in range.
        assert InputNumberElement(id="in", value=1e9).validate() == ()

    def test_is_an_abc_element(self) -> None:
        assert isinstance(InputNumberElement(id="in"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert InputNumberElement(id="in").child_elements() == ()

    def test_inverted_range_reports_one_error(self) -> None:
        errors = InputNumberElement(id="in", min=100.0, max=0.0, value=0.0).validate()
        assert len(errors) == 1
        assert "min" in errors[0].message
        assert errors[0].element_kind == "input_number"

    def test_out_of_range_value_reports_one_error(self) -> None:
        errors = InputNumberElement(id="in", value=150.0, min=0.0, max=100.0).validate()
        assert len(errors) == 1
        assert "value" in errors[0].message

    def test_out_of_range_against_lower_bound_only(self) -> None:
        # Only ``min`` present: the value below it reports, and the message names
        # a half-open range rather than crashing on the absent upper bound.
        errors = InputNumberElement(id="in", value=-5.0, min=0.0).validate()
        assert len(errors) == 1
        assert "value" in errors[0].message

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_value_is_reported(self, bad: float) -> None:
        errors = InputNumberElement(id="in", value=bad, min=0.0, max=100.0).validate()
        assert any("finite" in e.message for e in errors)

    def test_negative_step_is_reported(self) -> None:
        errors = InputNumberElement(id="in", value=1.0, step=-1.0).validate()
        assert any("step" in e.message for e in errors)

    def test_zero_step_is_the_no_buttons_value(self) -> None:
        # ``step == 0`` is the documented "no stepper buttons" value, not an error.
        assert not any(
            "step" in e.message
            for e in InputNumberElement(id="in", value=1.0, step=0.0).validate()
        )

    @pytest.mark.parametrize("fmt", ["", "no-percent", "%d %d", "%", "%*f", "%.*f"])
    def test_malformed_float_format_is_reported(self, fmt: str) -> None:
        errors = InputNumberElement(id="in", value=1.0, format=fmt).validate()
        assert any("format" in e.message for e in errors)

    @pytest.mark.parametrize("fmt", ["%.3f", "%g", "%.0f%%", "%8.2f"])
    def test_valid_float_format_passes(self, fmt: str) -> None:
        errors = InputNumberElement(id="in", value=1.0, format=fmt).validate()
        assert not any("format" in e.message for e in errors)

    def test_integer_variant_rejects_non_integral_bounds(self) -> None:
        # ``input_int`` truncates its bounds, so non-integral bounds would let a
        # committed integer fall outside the range the Hub re-checks.
        errors = InputNumberElement(
            id="in", min=0.1, max=0.2, value=0.15, integer=True
        ).validate()
        messages = " ".join(e.message for e in errors)
        assert "min" in messages
        assert "max" in messages
        assert "whole number" in messages

    def test_integer_variant_rejects_non_integral_step(self) -> None:
        errors = InputNumberElement(
            id="in", value=0.0, step=0.5, integer=True
        ).validate()
        assert any("whole number" in e.message and "step" in e.message for e in errors)

    def test_integer_variant_accepts_integral_valued_floats(self) -> None:
        errors = InputNumberElement(
            id="in", min=0.0, max=10.0, value=3.0, integer=True
        ).validate()
        assert not any("whole number" in e.message for e in errors)

    def test_float_variant_accepts_non_integral_bounds(self) -> None:
        errors = InputNumberElement(id="in", min=0.1, max=0.2, value=0.15).validate()
        assert errors == ()

    def test_valid_input_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([InputNumberElement(id="in")]).ok


class TestShowRejectsInvalidInput:
    @patch(_CLIENT_GET)
    def test_show_rejects_inverted_range(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1", [{"kind": "input_number", "id": "in", "min": 100.0, "max": 0.0}]
        )
        assert result.startswith("error: scene not rendered")
        assert "[input_number 'in']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_nan_value(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "input_number", "id": "in", "value": math.nan}])
        assert result.startswith("error: scene not rendered")
        assert "[input_number 'in']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_negative_step(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "input_number", "id": "in", "step": -1.0}])
        assert result.startswith("error: scene not rendered")
        assert "[input_number 'in']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_input_nested_in_group(self, mock_get: MagicMock) -> None:
        """A bad input nested in an all-ABC group is collected by the walk."""
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
                        {"kind": "input_number", "id": "bad", "min": 10.0, "max": 0.0},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[input_number 'bad']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_input_nested_in_collapsing_header(
        self, mock_get: MagicMock
    ) -> None:
        """A bad input nested in a collapsing_header is collected by the walk."""
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
                        {"kind": "input_number", "id": "bad", "min": 10.0, "max": 0.0},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[input_number 'bad']" in result
        client.show.assert_not_called()


# -- mutable-bounds patch rule (validate at the boundary, not per setter) ----


class TestPatchPath:
    def test_apply_patch_advances_value_in_place(self) -> None:
        n = InputNumberElement(id="in", value=25.0, min=0.0, max=100.0)
        returned = n.apply_patch({"value": 75.0})
        assert returned is n
        assert n.value == 75.0

    def test_combined_patch_value_then_widening_max_is_accepted(self) -> None:
        n = InputNumberElement(id="in", value=50.0, min=0.0, max=100.0)
        n.apply_patch({"value": 150.0, "max": 200.0})
        assert n.value == 150.0
        assert n.max == 200.0

    def test_apply_patch_clears_a_bound_to_none(self) -> None:
        # A ``None`` patch clears the bound — the value is now unbounded above.
        n = InputNumberElement(id="in", value=150.0, min=0.0, max=200.0)
        n.apply_patch({"max": None})
        assert n.max is None

    def test_apply_patch_rejects_out_of_range_value_and_rolls_back(self) -> None:
        n = InputNumberElement(id="in", value=50.0, min=0.0, max=100.0)
        with pytest.raises(ValueError, match="value"):
            n.apply_patch({"value": 150.0})
        assert n.value == 50.0

    def test_apply_patch_rejects_nan_value_and_rolls_back(self) -> None:
        n = InputNumberElement(id="in", value=50.0, min=0.0, max=100.0)
        with pytest.raises(ValueError, match="finite"):
            n.apply_patch({"value": float("nan")})
        assert n.value == 50.0

    def test_apply_patch_rejects_non_number_value(self) -> None:
        n = InputNumberElement(id="in", value=25.0)
        with pytest.raises(TypeError, match="value"):
            n.apply_patch({"value": "fast"})
        assert n.value == 25.0

    def test_apply_patch_is_atomic_on_range_rejection(self) -> None:
        n = InputNumberElement(id="in", value=25.0, label="orig", min=0.0, max=100.0)
        with pytest.raises(ValueError, match="value"):
            n.apply_patch({"label": "new", "value": 150.0})
        assert n.label == "orig"
        assert n.value == 25.0

    def test_apply_patch_rejects_a_malformed_format_and_rolls_back(self) -> None:
        # apply_patch re-checks format, not just range: a printf with a ``*`` width
        # reads an unsupplied vararg, so the patch is rejected at the boundary
        # rather than installed to fault at the next render.
        n = InputNumberElement(id="in", value=1.0, format="%.3f")
        with pytest.raises(ValueError, match="format"):
            n.apply_patch({"format": "%*f"})
        assert n.format == "%.3f"

    def test_apply_patch_rejects_integer_flip_that_strands_a_float_format(self) -> None:
        # Flipping to the integer variant while the format stays float (``%.3f``
        # needs ``eEfFgGaA``, the int variant needs ``diouxX``) is rejected — the
        # cross-field invariant is judged for the whole element after the patch.
        n = InputNumberElement(id="in", value=3.0, format="%.3f")
        with pytest.raises(ValueError, match="format"):
            n.apply_patch({"integer": True})
        assert n.integer is False
        assert n.format == "%.3f"


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_input_number_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "input_number", "id": "in", "label": "N"}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(InputNumberElement(id="in", label="N", value=7.0).to_dict())
        assert isinstance(elem, InputNumberElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC input_number must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, InputNumberElement)
        assert r_elem.value == 7.0

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(InputNumberElement(id="in", label="N").to_dict())
        assert isinstance(elem, InputNumberElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, InputNumberElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_input_number_renderer_factory(self) -> None:
        scene = SceneMessage(id="s1", elements=[InputNumberElement(id="in", value=5.0)])
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        number = received.elements[0]
        assert isinstance(number, InputNumberElement)

        before = number._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert number._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_value_on_the_hub_copy(self) -> None:
        elem = _decode(InputNumberElement(id="in", label="N", value=10.0).to_dict())
        assert isinstance(elem, InputNumberElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("in"),
                owner_id=ClientId("c"),
                value=42.5,
            )
        )
        assert elem.value == 42.5

    def test_hub_driven_change_does_not_refire(self) -> None:
        # A Hub-set value must NOT emit a RemoteEventHandlerInvocation; a genuine
        # commit DOES emit exactly one, carrying the number.
        elem = _decode(InputNumberElement(id="in", label="N").to_dict())
        assert isinstance(elem, InputNumberElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"value": 30.0})
        assert sent == [], "a Hub-set value must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("in"),
                owner_id=ClientId("c"),
                value=63.5,
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "value_changed"
        assert sent[0].value == 63.5


# -- Level 5: introspection (render_path + resolved props) ------------------


class TestLevel5Introspection:
    def test_reports_abc_render_path(self) -> None:
        elem = _decode(InputNumberElement(id="in", value=42.0).to_dict())
        record = _record(_inspect(_server(), elem), "in")
        assert record["render_path"] == "abc"

    def test_resolved_props_read_back_including_defaults(self) -> None:
        elem = _decode(
            InputNumberElement(
                id="in", label="Qty", value=42.0, min=0.0, max=50.0, integer=True
            ).to_dict()
        )
        props = _record(_inspect(_server(), elem), "in")["props"]
        assert isinstance(props, dict)
        assert props == {
            "label": "Qty",
            "value": 42.0,
            "min": 0.0,
            "max": 50.0,
            # step omitted on the wire (None) -> stays None on the replica.
            "step": None,
            # No explicit format + integer=True derives the %d variant default.
            "format": "%d",
            "integer": True,
            "tooltip": None,
        }
