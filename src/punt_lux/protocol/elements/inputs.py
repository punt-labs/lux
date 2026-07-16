"""Inputs-family codec registration — wires each per-kind module's codec.

The only per-kind class still registered here is ``selectable.py``.
``button.py``, ``checkbox.py``, ``input_text.py``, ``input_number.py``,
``slider.py``, ``color_picker.py``, ``combo.py``, and ``radio.py`` are registered
separately through ``JsonElementFactory`` (Element ABC dispatch — see
``__init__.py``); their entries are removed here to avoid double registration.

The ``InputsRegistry`` class consolidates the remaining register calls behind a
single ``apply`` method so the package ``__init__`` does not grow as each family
migrates.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.selectable import SelectableElement

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
            "selectable",
            SelectableElement,
            SelectableElement.to_dict,
            SelectableElement.from_dict,
        )
