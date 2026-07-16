"""Wire-path tests: inputs elements flow through Display.apply unchanged.

The inputs migration adds each class to the matrix below. Every
migrated kind must satisfy:

1. ``isinstance(elem, Element)`` is True against the domain Protocol.
2. ``factory.element_from_dict({...})`` returns the typed class via the per-kind
   ``from_dict`` classmethod — no module-level helpers.
3. ``Display.apply(client, AddElement(scene, elem))`` returns ElementAdded
   and the snapshot reflects the element.
4. Wire round-trip: ``element_to_dict(elem)`` produces byte-identical output
   to the pre-migration codec (asserted at the corpus level by
   ``make snapshot-parity``).

Covers all nine inputs kinds: Button, Slider, Checkbox, Combo, InputText,
InputNumber, Radio, ColorPicker, Selectable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.domain import ElementId, SceneId
from punt_lux.domain.display import Display
from punt_lux.domain.element import Element
from punt_lux.domain.event import ElementAdded
from punt_lux.domain.event_protocol import Event as DomainEvent
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.update import AddElement
from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SelectableElement,
    SliderElement,
    element_to_dict,
)
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

# -- Element Protocol conformance ------------------------------------------


@pytest.mark.parametrize(
    "elem",
    [
        ButtonElement(id="b1", label="OK"),
        SliderElement(id="s1", label="Vol"),
        CheckboxElement(id="c1", label="Bold"),
        ComboElement(id="co1", label="Pick", items=["a", "b"], selected=0),
        InputTextElement(id="it1", label="Name"),
        InputNumberElement(id="in1", label="Age"),
        RadioElement(id="r1", label="Mode", items=["x", "y"], selected=1),
        ColorPickerElement(id="cp1", label="Fill"),
        SelectableElement(id="sel1", label="Item"),
    ],
)
def test_inputs_element_satisfies_element_protocol(elem: Element) -> None:
    assert isinstance(elem, Element)


# -- Per-kind to_dict / from_dict round-trip --------------------------------


def test_button_to_dict_includes_action_default_to_id_when_unset() -> None:
    elem = ButtonElement(id="b1", label="Save")
    payload = element_to_dict(elem)
    # ``action`` only emits when explicitly set; absent => renderer defaults to id.
    assert "action" not in payload
    assert payload["label"] == "Save"


def test_button_to_dict_emits_arrow_when_set() -> None:
    elem = ButtonElement(id="b1", label="", arrow="left")
    assert element_to_dict(elem)["arrow"] == "left"


def test_button_from_dict_round_trip() -> None:
    payload = {
        "kind": "button",
        "id": "b1",
        "label": "Go",
        "action": "submit",
        "disabled": True,
        "small": True,
    }
    elem = agent_element_factory().element_from_dict(payload)
    assert isinstance(elem, ButtonElement)
    assert elem.action == "submit"
    assert elem.disabled is True
    assert elem.small is True


def test_slider_round_trip_with_integer_flag() -> None:
    elem = SliderElement(id="s1", label="N", value=5.0, min=0.0, max=10.0, integer=True)
    payload = element_to_dict(elem)
    assert payload["integer"] is True
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, SliderElement)
    assert restored.integer is True


def test_checkbox_round_trip() -> None:
    elem = CheckboxElement(id="c1", label="Active", value=True)
    payload = element_to_dict(elem)
    assert payload == {
        "kind": "checkbox",
        "id": "c1",
        "label": "Active",
        "value": True,
    }
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, CheckboxElement)
    assert restored.value is True


def test_checkbox_encode_via_encoder_factory_does_not_raise() -> None:
    """Regression guard for the checkbox reconcile (foundation item 1).

    Before the reconcile, ``JsonEncoderFactory().encode(checkbox)`` raised
    ``TypeError`` and JSON encode only worked by falling through to an
    un-removed legacy ``InputsRegistry`` registration. The four coupled
    edits (remove from ``InputsRegistry``; add to ``JsonEncoderFactory``,
    ``_element_to_dict``, and ``_ABC_TYPES``) make the encoder factory the
    single encode path. This asserts it directly — if any edit regresses,
    the encoder factory raises here.
    """
    from punt_lux.protocol.encoder_factory import JsonEncoderFactory

    payload = JsonEncoderFactory().encode(
        CheckboxElement(id="c1", label="Bold", value=True)
    )
    assert payload == {"kind": "checkbox", "id": "c1", "label": "Bold", "value": True}


def test_checkbox_tooltip_round_trips_through_abc_path() -> None:
    """The per-kind ``JsonCheckboxEncoder`` owns tooltip emission.

    For ABC kinds ``_element_to_dict`` skips the generic trailing tooltip
    append, so the per-kind codec must emit and re-read tooltip itself. A
    checkbox with a tooltip therefore survives the encode/decode round-trip.
    """
    elem = CheckboxElement(id="c1", label="Bold", value=True, tooltip="toggle bold")
    payload = element_to_dict(elem)
    assert payload["tooltip"] == "toggle bold"
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, CheckboxElement)
    assert restored.tooltip == "toggle bold"
    assert restored.value is True


def test_checkbox_absent_from_legacy_codec_table() -> None:
    """No dual live path: the migrated ABC kinds leave the ``ElementCodec``.

    text/button/checkbox/dialog/slider decode and encode through the per-kind
    ABC path; leaving any of them in the legacy ``ElementCodec`` table would be
    two live registrations for one kind. A still-legacy input kind
    (``selectable``) remains registered as the negative control.
    """
    from punt_lux.protocol.elements import build_element_codec

    kinds = build_element_codec().registered_kinds
    assert "checkbox" not in kinds
    assert "button" not in kinds
    assert "text" not in kinds
    assert "slider" not in kinds
    assert "selectable" in kinds


def test_combo_round_trip_with_items() -> None:
    elem = ComboElement(id="co1", label="Pick", items=["x", "y", "z"], selected=2)
    payload = element_to_dict(elem)
    assert payload["items"] == ["x", "y", "z"]
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, ComboElement)
    assert restored.selected == 2


def test_input_text_round_trip_strips_empty_hint() -> None:
    elem = InputTextElement(id="it1", label="Name", value="Ada")
    payload = element_to_dict(elem)
    assert "hint" not in payload
    restored = agent_element_factory().element_from_dict(
        {**payload, "hint": "type a name"}
    )
    assert isinstance(restored, InputTextElement)
    assert restored.hint == "type a name"


def test_input_number_emits_optional_bounds_only_when_set() -> None:
    elem = InputNumberElement(id="in1", label="N", min=0.0, max=100.0, step=1.0)
    payload = element_to_dict(elem)
    assert payload["min"] == 0.0
    assert payload["max"] == 100.0
    assert payload["step"] == 1.0
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, InputNumberElement)
    assert restored.min == 0.0


def test_input_number_unbounded_omits_min_max_step() -> None:
    elem = InputNumberElement(id="in1", label="N")
    payload = element_to_dict(elem)
    assert "min" not in payload
    assert "max" not in payload
    assert "step" not in payload


def test_radio_round_trip() -> None:
    elem = RadioElement(id="r1", label="Mode", items=["fast", "slow"], selected=1)
    payload = element_to_dict(elem)
    assert payload["items"] == ["fast", "slow"]
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, RadioElement)
    assert restored.selected == 1


def test_color_picker_round_trip_alpha_and_picker() -> None:
    elem = ColorPickerElement(
        id="cp1", label="Fill", value="#FF8080AA", alpha=True, picker=True
    )
    payload = element_to_dict(elem)
    assert payload["alpha"] is True
    assert payload["picker"] is True
    restored = agent_element_factory().element_from_dict(payload)
    assert isinstance(restored, ColorPickerElement)
    assert restored.value == "#FF8080AA"


def test_selectable_omits_selected_when_false() -> None:
    elem = SelectableElement(id="sel1", label="Item")
    payload = element_to_dict(elem)
    assert "selected" not in payload


def test_selectable_emits_selected_when_true() -> None:
    elem = SelectableElement(id="sel1", label="Item", selected=True)
    payload = element_to_dict(elem)
    assert payload["selected"] is True


# -- end-to-end through Display.apply ---------------------------------------


def test_every_inputs_kind_flows_through_display_apply() -> None:
    """PY-RF-2: every domain-routed wire kind has a production caller from day one."""
    display = Display()
    client = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    elements: list[Element] = [
        ButtonElement(id="b1", label="OK"),
        SliderElement(id="s1", label="Vol"),
        CheckboxElement(id="c1", label="Bold"),
        ComboElement(id="co1", label="Pick", items=["a"], selected=0),
        InputTextElement(id="it1", label="Name"),
        InputNumberElement(id="in1", label="N"),
        RadioElement(id="r1", label="Mode", items=["x"], selected=0),
        ColorPickerElement(id="cp1", label="Fill"),
        SelectableElement(id="sel1", label="Item"),
    ]
    for elem in elements:
        result = display.apply(client, AddElement(scene_id=SceneId("s1"), element=elem))
        assert isinstance(result, ElementAdded), elem

    snap = display.snapshot(SceneId("s1"))
    assert snap.element_ids == frozenset({ElementId(e.id) for e in elements})


# -- Button-interaction-routing (contract acceptance from PR 1) -----------


def test_button_click_routes_through_display_to_element_handlers() -> None:
    """Contract: construct Display, AddElement Button, simulate click, observe event.

    A wire ``RemoteEventHandlerInvocation`` passed to ``Display.interact`` lands on
    the resolved Element's handler registry — every registered handler
    fires exactly once, snapshot remains unchanged.
    """
    display = Display()
    alice = display.connect_client(name="alice")
    display.add_scene(SceneId("s1"))

    button = ButtonElement(id="b1", label="OK")
    add_result = display.apply(
        alice, AddElement(scene_id=SceneId("s1"), element=button)
    )
    assert isinstance(add_result, ElementAdded)

    observed_a: list[DomainEvent] = []
    observed_b: list[DomainEvent] = []
    button.add_handler(ButtonClicked, observed_a.append)
    button.add_handler(ButtonClicked, observed_b.append)

    msg = RemoteEventHandlerInvocation(
        element_id="b1",
        action="b1",
        value=True,
        scene_id="s1",
    )
    click_event = display.interact(alice, msg)

    assert isinstance(click_event, ButtonClicked)
    assert click_event.element_id == ElementId("b1")
    assert click_event.owner_id == alice
    assert observed_a == [click_event]
    assert observed_b == [click_event]

    snap = display.snapshot(SceneId("s1"))
    stored = snap.element(ElementId("b1"))
    assert isinstance(stored, ButtonElement)
    assert stored.label == "OK"


# -- inputs.py is now an aggregator only ------------------------------------


def test_inputs_module_holds_only_registration() -> None:
    """inputs.py is a thin registration shim; the only class is InputsRegistry."""
    from punt_lux.protocol.elements import inputs

    assert hasattr(inputs, "InputsRegistry")
    assert inputs.__all__ == ["InputsRegistry"]


def test_inputs_codec_helpers_are_gone_from_every_per_kind_module() -> None:
    """PL-PP-1 + PY-OO-7: no module-level `_*_to_dict` / `_*_from_dict` helpers.

    Walks each per-input module's AST and verifies it defines no top-level
    function whose name matches the deleted codec helper pattern.  This is
    the migration's structural promise: codec lives on the class.
    """
    from punt_lux.protocol import elements

    elements_dir = Path(elements.__file__).parent
    kinds = (
        "button",
        "slider",
        "checkbox",
        "combo",
        "input_text",
        "input_number",
        "radio",
        "color_picker",
        "selectable",
    )
    for kind in kinds:
        source = (elements_dir / f"{kind}.py").read_text()
        tree = ast.parse(source)
        top_level_funcs = [
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        ]
        bad = [
            name
            for name in top_level_funcs
            if name.endswith(("_to_dict", "_from_dict"))
        ]
        assert not bad, f"{kind}.py still has module-level codec helpers: {bad}"


# -- SFH: wire-boundary type checks on inputs from_dict --------------------


def test_button_rejects_non_string_id() -> None:
    with pytest.raises(ValueError, match=r"button element.*'id'"):
        ButtonElement.from_dict({"id": 7, "label": "OK"})


def test_button_rejects_non_bool_disabled() -> None:
    with pytest.raises(ValueError, match=r"button element.*'disabled'"):
        ButtonElement.from_dict({"id": "b1", "label": "OK", "disabled": "yes"})


def test_slider_rejects_non_numeric_value() -> None:
    with pytest.raises(ValueError, match=r"slider element.*'value'"):
        SliderElement.from_dict({"id": "s1", "label": "x", "value": "ten"})


def test_checkbox_rejects_non_bool_value() -> None:
    with pytest.raises(ValueError, match=r"checkbox element.*'value'"):
        CheckboxElement.from_dict({"id": "c1", "label": "x", "value": 1})


def test_combo_rejects_non_list_items() -> None:
    with pytest.raises(ValueError, match=r"combo element.*'items'"):
        ComboElement.from_dict({"id": "co1", "label": "x", "items": "abc"})


def test_combo_rejects_non_string_item() -> None:
    with pytest.raises(ValueError, match=r"combo element.*'items\[1\]'"):
        ComboElement.from_dict({"id": "co1", "label": "x", "items": ["a", 2]})


def test_input_number_rejects_non_numeric_step() -> None:
    with pytest.raises(ValueError, match=r"input_number element.*'step'"):
        InputNumberElement.from_dict({"id": "in1", "label": "N", "step": "fast"})


def test_input_number_accepts_null_bounds() -> None:
    """``null`` and absent are equivalent for nullable optional fields."""
    elem = InputNumberElement.from_dict(
        {"id": "in1", "label": "N", "min": None, "max": None, "step": None}
    )
    assert elem.min is None
    assert elem.max is None
    assert elem.step is None


def test_radio_rejects_non_int_selected() -> None:
    with pytest.raises(ValueError, match=r"radio element.*'selected'"):
        RadioElement.from_dict({"id": "r1", "label": "x", "selected": "first"})


def test_color_picker_rejects_non_bool_alpha() -> None:
    with pytest.raises(ValueError, match=r"color_picker element.*'alpha'"):
        ColorPickerElement.from_dict({"id": "cp1", "label": "x", "alpha": 1})


def test_selectable_rejects_non_bool_selected() -> None:
    with pytest.raises(ValueError, match=r"selectable element.*'selected'"):
        SelectableElement.from_dict({"id": "sel1", "label": "x", "selected": "yes"})


def test_input_text_round_trip_through_element_from_dict() -> None:
    payload = {
        "kind": "input_text",
        "id": "it1",
        "label": "Name",
        "value": "Ada",
        "hint": "type something",
    }
    elem = agent_element_factory().element_from_dict(payload)
    assert isinstance(elem, InputTextElement)
    assert elem.value == "Ada"
    assert elem.hint == "type something"
