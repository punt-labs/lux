"""Interactive input elements — buttons, sliders, checkboxes, pickers, fields."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from punt_lux.protocol.elements.basics import _strip_none

__all__ = [
    "ButtonElement",
    "CheckboxElement",
    "ColorPickerElement",
    "ComboElement",
    "InputNumberElement",
    "InputTextElement",
    "RadioElement",
    "SelectableElement",
    "SliderElement",
]


@dataclass(frozen=True, slots=True)
class ButtonElement:
    """A clickable button.

    Variants:
      - ``small=True``: compact button (ImGui SmallButton)
      - ``arrow``: directional arrow button ("left"/"right"/"up"/"down")
    """

    id: str
    label: str
    kind: Literal["button"] = "button"
    action: str | None = None
    disabled: bool = False
    small: bool = False
    arrow: str | None = None  # "left", "right", "up", "down"
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SliderElement:
    """A numeric slider."""

    id: str
    label: str
    kind: Literal["slider"] = "slider"
    value: float = 0.0
    min: float = 0.0
    max: float = 100.0
    format: str = "%.1f"
    integer: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class CheckboxElement:
    """A boolean checkbox."""

    id: str
    label: str
    kind: Literal["checkbox"] = "checkbox"
    value: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ComboElement:
    """A dropdown combo box."""

    id: str
    label: str
    kind: Literal["combo"] = "combo"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class InputTextElement:
    """A single-line text input."""

    id: str
    label: str
    kind: Literal["input_text"] = "input_text"
    value: str = ""
    hint: str = ""
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class RadioElement:
    """A set of radio buttons."""

    id: str
    label: str
    kind: Literal["radio"] = "radio"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class InputNumberElement:
    """A numeric input field with optional step buttons and clamping."""

    id: str
    label: str
    kind: Literal["input_number"] = "input_number"
    value: float = 0.0
    min: float | None = None
    max: float | None = None
    step: float | None = None
    format: str = "%.3f"
    integer: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ColorPickerElement:
    """A color picker with optional alpha channel and full picker mode.

    Modes:
      - default: inline ``ColorEdit3`` (RGB)
      - ``alpha=True``: ``ColorEdit4`` (RGBA), value uses ``#RRGGBBAA``
      - ``picker=True``: full ``ColorPicker3``/``ColorPicker4`` widget
    """

    id: str
    label: str
    kind: Literal["color_picker"] = "color_picker"
    value: str = "#FFFFFF"
    alpha: bool = False
    picker: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SelectableElement:
    """A toggleable list item."""

    id: str
    label: str
    kind: Literal["selectable"] = "selectable"
    selected: bool = False
    tooltip: str | None = None


def _button_to_dict(elem: ButtonElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "action": elem.action,
    }
    if elem.disabled:
        d["disabled"] = True
    if elem.small:
        d["small"] = True
    if elem.arrow is not None:
        d["arrow"] = elem.arrow
    return _strip_none(d)


def _slider_to_dict(elem: SliderElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
        "min": elem.min,
        "max": elem.max,
        "format": elem.format,
    }
    if elem.integer:
        d["integer"] = True
    return d


def _checkbox_to_dict(elem: CheckboxElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }


def _combo_to_dict(elem: ComboElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _input_text_to_dict(elem: InputTextElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }
    if elem.hint:
        d["hint"] = elem.hint
    return d


def _radio_to_dict(elem: RadioElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _input_number_to_dict(elem: InputNumberElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
        "format": elem.format,
    }
    if elem.min is not None:
        d["min"] = elem.min
    if elem.max is not None:
        d["max"] = elem.max
    if elem.step is not None:
        d["step"] = elem.step
    if elem.integer:
        d["integer"] = True
    return d


def _color_picker_to_dict(elem: ColorPickerElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }
    if elem.alpha:
        d["alpha"] = True
    if elem.picker:
        d["picker"] = True
    return d


def _selectable_to_dict(elem: SelectableElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
    }
    if elem.selected:
        d["selected"] = True
    return d


def _button_from_dict(d: dict[str, Any]) -> ButtonElement:
    return ButtonElement(
        id=d["id"],
        label=d.get("label", ""),
        action=d.get("action"),
        disabled=d.get("disabled", False),
        small=d.get("small", False),
        arrow=d.get("arrow"),
    )


def _slider_from_dict(d: dict[str, Any]) -> SliderElement:
    return SliderElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", 0.0),
        min=d.get("min", 0.0),
        max=d.get("max", 100.0),
        format=d.get("format", "%.1f"),
        integer=d.get("integer", False),
    )


def _checkbox_from_dict(d: dict[str, Any]) -> CheckboxElement:
    return CheckboxElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", False),
    )


def _combo_from_dict(d: dict[str, Any]) -> ComboElement:
    return ComboElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _input_text_from_dict(d: dict[str, Any]) -> InputTextElement:
    return InputTextElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", ""),
        hint=d.get("hint", ""),
    )


def _radio_from_dict(d: dict[str, Any]) -> RadioElement:
    return RadioElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _input_number_from_dict(d: dict[str, Any]) -> InputNumberElement:
    return InputNumberElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", 0.0),
        min=d.get("min"),
        max=d.get("max"),
        step=d.get("step"),
        format=d.get("format", "%.3f"),
        integer=d.get("integer", False),
    )


def _color_picker_from_dict(d: dict[str, Any]) -> ColorPickerElement:
    return ColorPickerElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", "#FFFFFF"),
        alpha=d.get("alpha", False),
        picker=d.get("picker", False),
    )


def _selectable_from_dict(d: dict[str, Any]) -> SelectableElement:
    return SelectableElement(
        id=d["id"],
        label=d.get("label", ""),
        selected=d.get("selected", False),
    )


SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    ButtonElement: _button_to_dict,
    SliderElement: _slider_to_dict,
    CheckboxElement: _checkbox_to_dict,
    ComboElement: _combo_to_dict,
    InputTextElement: _input_text_to_dict,
    InputNumberElement: _input_number_to_dict,
    RadioElement: _radio_to_dict,
    ColorPickerElement: _color_picker_to_dict,
    SelectableElement: _selectable_to_dict,
}

DESERIALIZERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "button": _button_from_dict,
    "slider": _slider_from_dict,
    "checkbox": _checkbox_from_dict,
    "combo": _combo_from_dict,
    "input_text": _input_text_from_dict,
    "input_number": _input_number_from_dict,
    "radio": _radio_from_dict,
    "color_picker": _color_picker_from_dict,
    "selectable": _selectable_from_dict,
}
