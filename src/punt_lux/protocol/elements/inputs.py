"""Inputs-family codec registration — wires each per-kind module's codec.

Per-kind classes live in ``slider.py``, ``checkbox.py``, ``combo.py``,
``input_text.py``, ``input_number.py``, ``radio.py``, ``color_picker.py``,
``selectable.py``.  ``button.py`` is registered separately through
``JsonElementFactory`` (Element ABC dispatch — see ``__init__.py``);
the entry is removed here to avoid double registration.

The ``InputsRegistry`` class consolidates the eight remaining register
calls behind a single ``apply`` method so the package ``__init__`` does
not grow as each family migrates.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.slider import SliderElement

__all__ = ["InputsRegistry"]


class InputsRegistry:
    """Registers every inputs-family element kind's codec into a Register sink.

    Mirrors ``BasicsRegistry`` — exists to give this module a
    class-with-behavior surface (PY-OO-1).  The class is stateless; its
    only behavior is wiring the per-kind codecs into a shared dispatch
    table at import time.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def apply(self, register: Register) -> None:
        """Register every inputs-family element kind's codec."""
        register(
            "slider", SliderElement, SliderElement.to_dict, SliderElement.from_dict
        )
        register(
            "checkbox",
            CheckboxElement,
            CheckboxElement.to_dict,
            CheckboxElement.from_dict,
        )
        register("combo", ComboElement, ComboElement.to_dict, ComboElement.from_dict)
        register(
            "input_text",
            InputTextElement,
            InputTextElement.to_dict,
            InputTextElement.from_dict,
        )
        register(
            "input_number",
            InputNumberElement,
            InputNumberElement.to_dict,
            InputNumberElement.from_dict,
        )
        register("radio", RadioElement, RadioElement.to_dict, RadioElement.from_dict)
        register(
            "color_picker",
            ColorPickerElement,
            ColorPickerElement.to_dict,
            ColorPickerElement.from_dict,
        )
        register(
            "selectable",
            SelectableElement,
            SelectableElement.to_dict,
            SelectableElement.from_dict,
        )
