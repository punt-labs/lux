"""The test-mode auto-clicker: one synthetic interaction per interactive element."""

from __future__ import annotations

from punt_lux.display.auto_click import AutoClicker
from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputTextElement,
    RadioElement,
    RemoteEventHandlerInvocation,
    SceneMessage,
    SelectableElement,
    SeparatorElement,
    SliderElement,
    TextElement,
)
from punt_lux.protocol.elements import Element


def _emitted(*elems: Element) -> list[RemoteEventHandlerInvocation]:
    sent: list[RemoteEventHandlerInvocation] = []
    msg = SceneMessage(id="s1", elements=list(elems), frame_id="f1")
    AutoClicker(sent.append).click_all(msg)
    return sent


def test_a_button_reports_a_click_carrying_its_action() -> None:
    (event,) = _emitted(ButtonElement(id="b1", label="Go", action="go"))
    assert (event.element_id, event.action) == ("b1", "go")
    assert event.event_kind == "button_clicked"
    assert event.value is True
    assert event.ts is not None


def test_a_button_without_an_action_reports_its_id() -> None:
    (event,) = _emitted(ButtonElement(id="b1", label="Go"))
    assert event.action == "b1"


def test_a_disabled_button_is_not_clicked() -> None:
    assert _emitted(ButtonElement(id="b1", label="Go", disabled=True)) == []


def test_an_inert_element_reports_nothing() -> None:
    assert _emitted(TextElement(id="t1", content="hi"), SeparatorElement(id="s")) == []


def test_a_slider_reports_its_value_typed_by_its_own_integer_flag() -> None:
    (real,) = _emitted(SliderElement(id="s1", value=2.5))
    (whole,) = _emitted(SliderElement(id="s2", value=2.5, integer=True))
    assert real.value == 2.5
    assert whole.value == 2
    assert (real.action, real.event_kind) == ("changed", "value_changed")


def test_a_checkbox_reports_the_value_the_click_leaves_behind() -> None:
    (event,) = _emitted(CheckboxElement(id="c1", value=False))
    assert event.value is True
    assert event.action == "changed"


def test_a_selectable_reports_the_selection_the_click_leaves_behind() -> None:
    (event,) = _emitted(SelectableElement(id="sel", selected=False))
    assert (event.action, event.value) == ("clicked", True)


def test_a_combo_and_a_radio_report_their_selected_index() -> None:
    (combo,) = _emitted(ComboElement(id="c", items=["a", "b"], selected=1))
    (radio,) = _emitted(RadioElement(id="r", items=["a", "b"], selected=1))
    assert combo.value == 1
    assert radio.value == 1


def test_a_text_input_and_a_color_picker_report_their_current_value() -> None:
    (text,) = _emitted(InputTextElement(id="i", value="typed"))
    (color,) = _emitted(ColorPickerElement(id="p", value="#00FF00"))
    assert text.value == "typed"
    assert color.value == "#00FF00"


def test_every_interactive_element_of_a_scene_is_visited() -> None:
    events = _emitted(
        ButtonElement(id="b", label="Go"),
        TextElement(id="t", content="hi"),
        CheckboxElement(id="c"),
    )
    assert [e.element_id for e in events] == ["b", "c"]
