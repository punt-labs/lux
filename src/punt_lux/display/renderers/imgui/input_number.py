"""ImGuiInputNumberRenderer — Renderer-Protocol adapter for ``InputNumberElement``.

A leaf: paints through a per-paint ``InputNumberRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
edit and fires ``ValueChanged`` on commit (wrapped for D21 remote dispatch).
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.input_number_renderer import InputNumberRenderer
from punt_lux.protocol.elements.input_number import InputNumberElement

__all__ = ["ImGuiInputNumberRenderer"]


@final
class ImGuiInputNumberRenderer(LeafRenderer[InputNumberElement]):
    """Paint an InputNumberElement via a per-paint InputNumberRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the input (fires ValueChanged on commit)."""
        InputNumberRenderer(self._factory.widget_state).render(self._elem)
