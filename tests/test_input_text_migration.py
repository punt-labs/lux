"""Migration gate for the ABC ``input_text`` — an interactive text input.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the built-in
state-sync, the wire-boundary rejection, and the echo-suppression safety
property. The interactive value flows as a ``str`` payload on ``ValueChanged``,
mirroring the checkbox's ``bool`` payload.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.display import Display
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.event import ElementAdded
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.interaction_errors import WrongKindError
from punt_lux.domain.update import AddElement
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import InputTextElement, build_element_codec
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse


def _decode(wire: Mapping[str, object]) -> object:
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_roundtrips_to_abc(self) -> None:
        elem = InputTextElement(id="it", label="Name", value="Ada", hint="who?")
        restored = _decode(elem.to_dict())
        assert isinstance(restored, InputTextElement)
        assert restored.id == "it"
        assert restored.label == "Name"
        assert restored.value == "Ada"
        assert restored.hint == "who?"

    def test_empty_hint_is_omitted_on_the_wire(self) -> None:
        payload = InputTextElement(id="it", label="N", value="x").to_dict()
        assert "hint" not in payload
        assert payload == {"kind": "input_text", "id": "it", "label": "N", "value": "x"}

    def test_tooltip_round_trips(self) -> None:
        elem = InputTextElement(id="it", label="N", value="x", tooltip="hover")
        restored = _decode(elem.to_dict())
        assert isinstance(restored, InputTextElement)
        assert restored.tooltip == "hover"

    def test_absent_tooltip_stays_none(self) -> None:
        restored = _decode(InputTextElement(id="it", label="N").to_dict())
        assert isinstance(restored, InputTextElement)
        assert restored.tooltip is None

    def test_encoder_factory_encodes_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(
            InputTextElement(id="it", label="N", value="v")
        )
        assert encoded == {"kind": "input_text", "id": "it", "label": "N", "value": "v"}

    def test_absent_from_legacy_codec_table(self) -> None:
        # No dual live path: the migrated kind leaves the ``ElementCodec`` table.
        # A still-legacy input (``spinner``) stays the negative control.
        kinds = build_element_codec().registered_kinds
        assert "input_text" not in kinds
        assert "spinner" in kinds


# -- wire-boundary rejection (reject, do not silently coerce) ----------------


class TestMalformedWireRejected:
    def test_non_string_value_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"input_text element.*'value'"):
            InputTextElement.from_dict({"id": "it", "label": "N", "value": 7})

    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"input_text element.*'id'"):
            InputTextElement.from_dict({"label": "N", "value": "x"})

    def test_non_list_handlers_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            InputTextElement.from_dict(
                {"id": "it", "label": "N", "handlers": {"not": "a list"}}
            )


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_input_text_has_no_errors(self) -> None:
        elem = InputTextElement(id="it", label="N", value="x")
        assert ElementTreeValidator().validate_tree([elem]).ok

    def test_is_an_abc_element(self) -> None:
        assert isinstance(InputTextElement(id="it"), AbcElement)

    def test_leaf_has_no_children(self) -> None:
        assert InputTextElement(id="it").child_elements() == ()


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_input_text_is_a_migrated_abc_kind(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "input_text", "id": "it", "label": "N"}],
        }
        assert ContainerAbcGate.is_all_abc(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_crosses_as_pickled_entry(self) -> None:
        elem = _decode(InputTextElement(id="it", label="N", value="v").to_dict())
        assert isinstance(elem, InputTextElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC input_text must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, InputTextElement)
        assert r_elem.value == "v"

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        elem = _decode(InputTextElement(id="it", label="N").to_dict())
        assert isinstance(elem, InputTextElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[elem]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_elem = restored.elements[0]
        assert isinstance(r_elem, InputTextElement)
        assert r_elem.handler_count(ValueChanged) == 1


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_value_on_the_hub_copy(self) -> None:
        elem = _decode(InputTextElement(id="it", label="N", value="old").to_dict())
        assert isinstance(elem, InputTextElement)
        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("it"),
                owner_id=ClientId("c"),
                value="new",
            )
        )
        assert elem.value == "new"

    def test_hub_driven_change_does_not_refire(self) -> None:
        # ECHO-SUPPRESSION: a Hub-set value (a re-push's new state) must NOT emit
        # a RemoteEventHandlerInvocation, or a fire -> Hub -> re-push -> fire loop
        # would run. A genuine edit DOES emit exactly one, carrying the text.
        elem = _decode(InputTextElement(id="it", label="N").to_dict())
        assert isinstance(elem, InputTextElement)
        sent: list[RemoteEventHandlerInvocation] = []
        elem.wrap_handlers_for_remote(sent.append)

        elem.apply_patch({"value": "hello"})
        assert sent == [], "a Hub-set value must not fire an interaction"

        elem.fire(
            ValueChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("it"),
                owner_id=ClientId("c"),
                value="typed",
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "value_changed"
        assert sent[0].value == "typed"


# -- Display.interact typed-event construction ------------------------------


class TestDisplayInteract:
    def test_str_value_builds_value_changed(self) -> None:
        display = Display()
        alice = display.connect_client(name="alice")
        display.add_scene(SceneId("s1"))
        elem = InputTextElement(id="it", label="N")
        assert isinstance(
            display.apply(alice, AddElement(scene_id=SceneId("s1"), element=elem)),
            ElementAdded,
        )
        event = display.interact(
            alice,
            RemoteEventHandlerInvocation(
                element_id="it", action="changed", value="hello", scene_id="s1"
            ),
        )
        assert isinstance(event, ValueChanged)
        assert event.value == "hello"

    def test_non_str_value_is_rejected(self) -> None:
        display = Display()
        alice = display.connect_client(name="alice")
        display.add_scene(SceneId("s1"))
        elem = InputTextElement(id="it", label="N")
        display.apply(alice, AddElement(scene_id=SceneId("s1"), element=elem))
        with pytest.raises(WrongKindError):
            display.interact(
                alice,
                RemoteEventHandlerInvocation(
                    element_id="it", action="changed", value=True, scene_id="s1"
                ),
            )


# -- Level 5: introspection (render_path + resolved props) ------------------


def _inspect(server: DisplayServer, elem: object) -> QueryResponse:
    from unittest.mock import MagicMock

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


class TestLevel5Introspection:
    def test_reports_abc_render_path_and_props(self) -> None:
        elem = _decode(
            InputTextElement(id="it", label="Name", value="Ada", hint="who?").to_dict()
        )
        assert isinstance(elem, InputTextElement)
        record = _record(_inspect(_server(), elem), "it")
        assert record["render_path"] == "abc"
        props = record["props"]
        assert isinstance(props, dict)
        assert props["value"] == "Ada"
        assert props["hint"] == "who?"
