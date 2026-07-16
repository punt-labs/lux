"""Migration gate for the ABC ``slider`` — an interactive numeric input.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, the wire-boundary rejection, and the mutable-bounds patch rule.
The interactive value flows as a ``float`` payload on ``ValueChanged`` (an
``int`` for the integer variant), mirroring the input_text ``str`` payload.
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
from punt_lux.protocol.elements import SliderElement, build_element_codec
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
        elem = SliderElement(
            id="sl", label="Vol", value=42.5, min=0.0, max=100.0, format="%.2f"
        )
        restored = _decode(elem.to_dict())
        assert isinstance(restored, SliderElement)
        assert restored.value == 42.5
        assert restored.min == 0.0
        assert restored.max == 100.0
        assert restored.format == "%.2f"

    def test_integer_variant_round_trips(self) -> None:
        elem = SliderElement(id="sl", label="N", value=5.0, max=10.0, integer=True)
        payload = elem.to_dict()
        assert payload["integer"] is True
        restored = _decode(payload)
        assert isinstance(restored, SliderElement)
        assert restored.integer is True

    def test_default_integer_omitted_on_the_wire(self) -> None:
        payload = SliderElement(id="sl", label="N").to_dict()
        assert "integer" not in payload
        assert payload == {
            "kind": "slider",
            "id": "sl",
            "label": "N",
            "value": 0.0,
            "min": 0.0,
            "max": 100.0,
            "format": "%.1f",
        }

    def test_tooltip_round_trips(self) -> None:
        elem = SliderElement(id="sl", label="N", tooltip="drag me")
        payload = elem.to_dict()
        assert payload["tooltip"] == "drag me"
        restored = _decode(payload)
        assert isinstance(restored, SliderElement)
        assert restored.tooltip == "drag me"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(SliderElement(id="sl", label="N").to_dict())
        assert isinstance(restored, SliderElement)
        assert restored.tooltip is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(SliderElement(id="sl", label="N"))
        assert encoded["kind"] == "slider"
        assert encoded["value"] == 0.0

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``radio``) stays registered as the negative control.
        kinds = build_element_codec().registered_kinds
        assert "slider" not in kinds
        assert "radio" in kinds


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_non_numeric_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"slider element.*'value'"):
            SliderElement.from_dict({"id": "sl", "label": "N", "value": "ten"})

    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"slider element.*'id'"):
            SliderElement.from_dict({"label": "N"})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            SliderElement.from_dict(
                {"id": "sl", "label": "N", "handlers": {"not": "a list"}}
            )


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_slider_has_no_errors(self) -> None:
        elem = SliderElement(id="sl", value=50.0, min=0.0, max=100.0)
        assert elem.validate() == ()

    def test_is_an_abc_element(self) -> None:
        assert isinstance(SliderElement(id="sl"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert SliderElement(id="sl").child_elements() == ()

    def test_inverted_range_reports_one_error(self) -> None:
        errors = SliderElement(id="sl", min=100.0, max=0.0, value=0.0).validate()
        assert len(errors) == 1
        assert "min" in errors[0].message
        assert errors[0].element_kind == "slider"

    def test_out_of_range_value_reports_one_error(self) -> None:
        errors = SliderElement(id="sl", value=150.0, min=0.0, max=100.0).validate()
        assert len(errors) == 1
        assert "value" in errors[0].message

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_value_is_reported(self, bad: float) -> None:
        errors = SliderElement(id="sl", value=bad, min=0.0, max=100.0).validate()
        assert any("finite" in e.message for e in errors)

    @pytest.mark.parametrize(
        "fmt", ["", "no-percent", "%d %d", "%", "%d", "%*f", "%.*f"]
    )
    def test_malformed_float_format_is_reported(self, fmt: str) -> None:
        # A default (float) slider rejects: no conversion, a literal-only string,
        # two conversions, a bare trailing "%", an int specifier ("%d") whose
        # family does not match the float variant, and star width/precision
        # ("%*f", "%.*f") that would read an unsupplied vararg.
        errors = SliderElement(id="sl", value=1.0, max=10.0, format=fmt).validate()
        assert any("format" in e.message for e in errors)

    @pytest.mark.parametrize("fmt", ["%.1f", "%g", "%.0f%%", "%8.2f"])
    def test_valid_float_format_passes(self, fmt: str) -> None:
        # One float conversion is accepted, including one beside an escaped
        # literal percent ("%.0f%%") that a naive percent count would reject and
        # numeric width/precision ("%8.2f").
        errors = SliderElement(id="sl", value=1.0, max=10.0, format=fmt).validate()
        assert not any("format" in e.message for e in errors)

    @pytest.mark.parametrize("fmt", ["%d", "%03d"])
    def test_valid_integer_format_passes(self, fmt: str) -> None:
        errors = SliderElement(
            id="sl", value=1.0, max=10.0, format=fmt, integer=True
        ).validate()
        assert not any("format" in e.message for e in errors)

    @pytest.mark.parametrize("fmt", ["%f", "%*d"])
    def test_malformed_integer_format_is_reported(self, fmt: str) -> None:
        # The integer variant renders via slider_int and needs the %d family, so
        # a float conversion ("%f") is the wrong family; a star width ("%*d")
        # would read an unsupplied vararg. Both are rejected.
        errors = SliderElement(
            id="sl", value=1.0, max=10.0, format=fmt, integer=True
        ).validate()
        assert any("format" in e.message for e in errors)

    def test_default_format_on_integer_slider_validates(self) -> None:
        # The Bugbot regression: a default-constructed integer slider (no explicit
        # format) derives "%d" and validates, rather than rejecting the float
        # default "%.1f" against the slider_int variant.
        elem = SliderElement(id="sl", value=1.0, max=10.0, integer=True)
        assert elem.format == "%d"
        assert not any("format" in e.message for e in elem.validate())

    def test_integer_slider_rejects_non_integral_bounds(self) -> None:
        # slider_int truncates its bounds to int, so non-integral bounds would let
        # a committed integer fall outside the float range the Hub re-checks. Both
        # bounds (and the in-range value, itself non-integral) are named.
        errors = SliderElement(
            id="sl", min=0.1, max=0.2, value=0.15, integer=True
        ).validate()
        messages = " ".join(e.message for e in errors)
        assert "min" in messages
        assert "max" in messages
        assert "whole number" in messages

    def test_integer_slider_rejects_non_integral_value(self) -> None:
        errors = SliderElement(
            id="sl", value=1.5, min=0.0, max=10.0, integer=True
        ).validate()
        assert len(errors) == 1
        assert "value" in errors[0].message
        assert "whole number" in errors[0].message

    def test_integer_slider_accepts_integral_valued_floats(self) -> None:
        # Integral floats (3.0, not 3) are fine — the truncation is lossless.
        errors = SliderElement(
            id="sl", min=0.0, max=10.0, value=3.0, integer=True
        ).validate()
        assert not any("whole number" in e.message for e in errors)

    def test_float_slider_accepts_non_integral_bounds(self) -> None:
        # The integrality rule is scoped to the integer variant; a float slider
        # with fractional bounds is unaffected.
        errors = SliderElement(id="sl", min=0.1, max=0.2, value=0.15).validate()
        assert errors == ()

    def test_valid_slider_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([SliderElement(id="sl")]).ok


class TestShowRejectsInvalidSlider:
    @patch(_CLIENT_GET)
    def test_show_rejects_inverted_range(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "slider", "id": "sl", "min": 100.0, "max": 0.0}])
        assert result.startswith("error: scene not rendered")
        assert "[slider 'sl']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_out_of_range_value(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1", [{"kind": "slider", "id": "sl", "value": 5.0, "min": 0.0, "max": 1.0}]
        )
        assert result.startswith("error: scene not rendered")
        assert "[slider 'sl']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_nan_value(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "slider", "id": "sl", "value": math.nan}])
        assert result.startswith("error: scene not rendered")
        assert "[slider 'sl']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_bad_format(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "slider", "id": "sl", "format": "no-percent"}])
        assert result.startswith("error: scene not rendered")
        assert "[slider 'sl']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_slider_nested_in_group(self, mock_get: MagicMock) -> None:
        """A bad slider nested in an all-ABC group is collected by the walk."""
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
                        {"kind": "slider", "id": "bad", "min": 10.0, "max": 0.0},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[slider 'bad']" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_slider_nested_in_collapsing_header(
        self, mock_get: MagicMock
    ) -> None:
        """A bad slider nested in a collapsing_header is collected by the walk."""
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
                        {"kind": "slider", "id": "bad", "min": 10.0, "max": 0.0},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[slider 'bad']" in result
        client.show.assert_not_called()


# -- mutable-bounds patch rule (validate at the boundary, not per setter) ----


class TestPatchPath:
    def test_apply_patch_advances_value_in_place(self) -> None:
        s = SliderElement(id="sl", value=25.0, min=0.0, max=100.0)
        returned = s.apply_patch({"value": 75.0})
        assert returned is s
        assert s.value == 75.0

    def test_combined_patch_value_then_widening_max_is_accepted(self) -> None:
        """The opposite-order combined patch a per-setter raise would wrongly reject.

        ``value`` 150 exceeds the current ``max`` 100, but the same patch widens
        ``max`` to 200. Applied value-first against the stale ``max``, a naive
        per-setter range raise trips on the value; the element-boundary re-check
        judges the final state and accepts it.
        """
        s = SliderElement(id="sl", value=50.0, min=0.0, max=100.0)
        s.apply_patch({"value": 150.0, "max": 200.0})
        assert s.value == 150.0
        assert s.max == 200.0

    def test_apply_patch_rejects_out_of_range_value_and_rolls_back(self) -> None:
        s = SliderElement(id="sl", value=50.0, min=0.0, max=100.0)
        with pytest.raises(ValueError, match="value"):
            s.apply_patch({"value": 150.0})
        assert s.value == 50.0

    def test_apply_patch_rejects_nan_value_and_rolls_back(self) -> None:
        s = SliderElement(id="sl", value=50.0, min=0.0, max=100.0)
        with pytest.raises(ValueError, match="finite"):
            s.apply_patch({"value": float("nan")})
        assert s.value == 50.0

    def test_apply_patch_rejects_non_number_value(self) -> None:
        s = SliderElement(id="sl", value=25.0)
        with pytest.raises(TypeError, match="value"):
            s.apply_patch({"value": "fast"})
        assert s.value == 25.0

    def test_apply_patch_rejects_flip_to_integer_over_non_integral_bounds(self) -> None:
        # Flipping integer False->True over existing fractional bounds is caught
        # by the same boundary re-check, and the flip rolls back.
        s = SliderElement(id="sl", min=0.1, max=0.9, value=0.5)
        with pytest.raises(ValueError, match="whole number"):
            s.apply_patch({"integer": True})
        assert s.integer is False

    def test_apply_patch_is_atomic_on_range_rejection(self) -> None:
        """A rejected multi-field patch leaves every field unchanged.

        ``label`` precedes ``value`` in dict order, so a naive loop would apply
        ``label`` before the range re-check rejects. The whole element rolls back.
        """
        s = SliderElement(id="sl", value=25.0, label="orig", min=0.0, max=100.0)
        with pytest.raises(ValueError, match="value"):
            s.apply_patch({"label": "new", "value": 150.0})
        assert s.label == "orig"
        assert s.value == 25.0


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_slider_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "slider", "id": "sl", "label": "N"}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(SliderElement(id="sl", label="N", value=7.0).to_dict())
        assert isinstance(elem, SliderElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC slider must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, SliderElement)
        assert r_elem.value == 7.0

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(SliderElement(id="sl", label="N").to_dict())
        assert isinstance(elem, SliderElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, SliderElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_slider_renderer_factory(self) -> None:
        scene = SceneMessage(id="s1", elements=[SliderElement(id="sl", value=5.0)])
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        slider = received.elements[0]
        assert isinstance(slider, SliderElement)

        before = slider._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert slider._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_value_on_the_hub_copy(self) -> None:
        elem = _decode(SliderElement(id="sl", label="N", value=10.0).to_dict())
        assert isinstance(elem, SliderElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("sl"),
                owner_id=ClientId("c"),
                value=42.5,
            )
        )
        assert elem.value == 42.5

    def test_hub_driven_change_does_not_refire(self) -> None:
        # A Hub-set value must NOT emit a RemoteEventHandlerInvocation; a genuine
        # commit DOES emit exactly one, carrying the float.
        elem = _decode(SliderElement(id="sl", label="N").to_dict())
        assert isinstance(elem, SliderElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"value": 30.0})
        assert sent == [], "a Hub-set value must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("sl"),
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
        elem = _decode(SliderElement(id="sl", value=42.0).to_dict())
        record = _record(_inspect(_server(), elem), "sl")
        assert record["render_path"] == "abc"

    def test_resolved_props_read_back_including_defaults(self) -> None:
        elem = _decode(
            SliderElement(
                id="sl", label="Vol", value=42.0, min=0.0, max=50.0, integer=True
            ).to_dict()
        )
        props = _record(_inspect(_server(), elem), "sl")["props"]
        assert isinstance(props, dict)
        assert props == {
            "label": "Vol",
            "value": 42.0,
            "min": 0.0,
            "max": 50.0,
            # No explicit format + integer=True derives the %d variant default.
            "format": "%d",
            "integer": True,
            "tooltip": None,
        }
