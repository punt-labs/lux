"""Migration gate for the ABC ``selectable`` — a bool-atomic interactive row.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, the wire-boundary rejection, and the capability guard. The
interactive value flows as a ``bool`` on ``ValueChanged`` — the checkbox pattern
with the ``selected`` wire key, no ``ContinuousEditArbiter``.

Unlike combo/radio there is no index invariant: a bool plus a label is always
well-formed, so ``validate()`` is vacuous (inherits the ABC no-error default)
and there is no ``apply_patch`` override. The only rejection is codec-level (a
non-bool ``selected`` at the wire boundary), so — unlike combo's out-of-range
index — there is no valid-but-invalid selectable for a ``show()``-time tree-walk
rejection.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import SelectableElement, build_element_codec
from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_kind_verify import AbcKindVerifier
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse


def _decode(wire: Mapping[str, object]) -> object:
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


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
        elem = SelectableElement(id="se", label="Bass boost", selected=True)
        restored = _decode(elem.to_dict())
        assert isinstance(restored, SelectableElement)
        assert restored.selected is True
        assert restored.label == "Bass boost"

    def test_always_emits_selected_even_when_false(self) -> None:
        # The design states the value; an unselected row still emits
        # ``selected: false`` (no legacy omit-when-false quirk).
        payload = SelectableElement(id="se", label="Item").to_dict()
        assert payload == {
            "kind": "selectable",
            "id": "se",
            "label": "Item",
            "selected": False,
        }

    def test_emits_selected_true(self) -> None:
        payload = SelectableElement(id="se", label="Item", selected=True).to_dict()
        assert payload["selected"] is True

    def test_tooltip_round_trips(self) -> None:
        # The legacy to_dict silently dropped tooltip; the ABC encoder keeps it.
        elem = SelectableElement(id="se", label="Item", tooltip="toggle me")
        payload = elem.to_dict()
        assert payload["tooltip"] == "toggle me"
        restored = _decode(payload)
        assert isinstance(restored, SelectableElement)
        assert restored.tooltip == "toggle me"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(SelectableElement(id="se", label="Item").to_dict())
        assert isinstance(restored, SelectableElement)
        assert restored.tooltip is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(SelectableElement(id="se", label="Item"))
        assert encoded["kind"] == "selectable"
        assert encoded["selected"] is False

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``spinner``) stays the negative control.
        kinds = build_element_codec().registered_kinds
        assert "selectable" not in kinds
        assert "spinner" in kinds


# -- capability guard: selectable cannot ship handler-less ------------------


class TestCapabilityGuard:
    def test_selectable_is_a_registered_interactive_kind(self) -> None:
        assert "selectable" in AbcKindNames.MIGRATED_ABC_KINDS
        assert "selectable" in AbcKindVerifier.INTERACTIVE_KINDS

    def test_guard_rejects_a_handler_less_selectable_spec(self) -> None:
        from punt_lux.protocol.elements.abc_kind_codec import KindCodec
        from punt_lux.protocol.elements.abc_leaf_spec import LeafKindSpec
        from punt_lux.protocol.elements.selectable_codec import (
            JsonSelectableDecoder,
            JsonSelectableEncoder,
        )

        registry = AbcElementRegistry()
        # A spec that forgets its handler_builder must fail the capability check.
        registry.register(
            LeafKindSpec(
                kind="selectable",
                codec=KindCodec(
                    SelectableElement,
                    JsonSelectableDecoder,
                    JsonSelectableEncoder().encode,
                ),
            )
        )
        with pytest.raises(RuntimeError, match="handlers"):
            AbcKindVerifier._verify_capabilities(registry)


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"selectable element.*'id'"):
            SelectableElement.from_dict({"label": "Item"})

    def test_non_bool_selected_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"selectable element.*'selected'"):
            SelectableElement.from_dict({"id": "se", "label": "x", "selected": "yes"})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            SelectableElement.from_dict(
                {"id": "se", "label": "x", "handlers": {"not": "a list"}}
            )


# -- self-validation (vacuous — a bool + label is always well-formed) --------


class TestSelfValidation:
    def test_valid_selectable_has_no_errors(self) -> None:
        assert SelectableElement(id="se", label="Item", selected=True).validate() == ()

    def test_unselected_selectable_has_no_errors(self) -> None:
        assert SelectableElement(id="se", label="Item").validate() == ()

    def test_is_an_abc_element(self) -> None:
        assert isinstance(SelectableElement(id="se"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert SelectableElement(id="se").child_elements() == ()

    def test_valid_selectable_passes_the_tree_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([SelectableElement(id="se")]).ok

    def test_valid_selectable_nested_in_group_passes_the_walk(self) -> None:
        # No index invariant, so a well-typed selectable never fails the walk —
        # the analogue of combo's out-of-range rejection does not exist here.
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [
                {"kind": "text", "id": "ok", "content": "fine"},
                {"kind": "selectable", "id": "row", "label": "Item", "selected": True},
            ],
        }
        elem = _decode(wire)
        assert ElementTreeValidator().validate_tree([cast("Any", elem)]).ok


# -- patch path (no cross-field invariant, so no boundary re-check) ----------


class TestPatchPath:
    def test_apply_patch_advances_selected_in_place(self) -> None:
        s = SelectableElement(id="se", label="Item", selected=False)
        returned = s.apply_patch({"selected": True})
        assert returned is s
        assert s.selected is True

    def test_apply_patch_rejects_non_bool_and_rolls_back(self) -> None:
        s = SelectableElement(id="se", label="Item", selected=True)
        with pytest.raises(TypeError, match="selected"):
            s.apply_patch({"selected": "on"})
        assert s.selected is True


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_selectable_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "selectable", "id": "row", "label": "Item"}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(SelectableElement(id="se", selected=True).to_dict())
        assert isinstance(elem, SelectableElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC selectable must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, SelectableElement)
        assert r_elem.selected is True

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(SelectableElement(id="se").to_dict())
        assert isinstance(elem, SelectableElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, SelectableElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_selectable_renderer_factory(self) -> None:
        scene = SceneMessage(id="s1", elements=[SelectableElement(id="se")])
        received = message_from_dict(message_to_dict(scene))
        assert isinstance(received, SceneMessage)
        selectable = received.elements[0]
        assert isinstance(selectable, SelectableElement)

        before = selectable._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert selectable._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_selection_on_the_hub_copy(self) -> None:
        elem = _decode(SelectableElement(id="se", selected=False).to_dict())
        assert isinstance(elem, SelectableElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("se"),
                owner_id=ClientId("c"),
                value=True,
            )
        )
        assert elem.selected is True

    def test_hub_driven_change_does_not_refire(self) -> None:
        # A Hub-set value must NOT emit a RemoteEventHandlerInvocation; a genuine
        # click DOES emit exactly one, carrying the bool value.
        elem = _decode(SelectableElement(id="se", selected=False).to_dict())
        assert isinstance(elem, SelectableElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"selected": True})
        assert sent == [], "a Hub-set value must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("se"),
                owner_id=ClientId("c"),
                value=False,
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "value_changed"
        assert sent[0].value is False


# -- Level 5: introspection (render_path + resolved props) ------------------


class TestLevel5Introspection:
    def test_reports_abc_render_path(self) -> None:
        elem = _decode(SelectableElement(id="se", selected=False).to_dict())
        record = _record(_inspect(_server(), elem), "se")
        assert record["render_path"] == "abc"

    def test_resolved_props_read_back_including_defaults(self) -> None:
        elem = _decode(
            SelectableElement(id="se", label="Bass", selected=True).to_dict()
        )
        props = _record(_inspect(_server(), elem), "se")["props"]
        assert isinstance(props, dict)
        assert props == {
            "label": "Bass",
            "selected": True,
            "tooltip": None,
        }
