"""``WidgetValueProvider`` — Protocol for elements that own widget-display state.

The scene-graph layer needs to read the current "value" off an input element
after a patch updates it, so that ``WidgetState`` mirrors the latest payload
the wire delivered.  Different input kinds spell "value" differently:

- ``Slider``, ``Checkbox``, ``InputText`` carry ``value``
- ``Combo``, ``Radio`` carry ``selected`` (an index)
- ``Selectable`` carries ``selected`` (a bool)
- ``ColorPicker`` initialises widget state with an ``ImVec4`` via the renderer's
  ``ensure()``; returning the hex string here would corrupt that state, so it
  does NOT implement the Protocol

A Protocol — not an ABC — keeps each input class free of inheritance and lets
``SceneManager`` dispatch via structural typing rather than naming concrete
element classes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["WidgetValueProvider"]


@runtime_checkable
class WidgetValueProvider(Protocol):
    """Element owning a widget-display value mirrored into WidgetState."""

    def widget_value(self) -> Any:
        """Return the value that should populate WidgetState after a patch."""
        ...
