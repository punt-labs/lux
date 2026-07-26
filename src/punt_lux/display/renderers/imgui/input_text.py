"""ImGuiInputTextRenderer — Renderer-Protocol adapter for ``InputTextElement``.

A leaf: paints through a per-paint ``InputTextRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
buffer and fires ``ValueChanged`` on a genuine edit (wrapped for D21 remote
dispatch). ``LeafRenderer`` adds the shared tooltip pass and the geometry capture
around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.input_text_renderer import InputTextRenderer
from punt_lux.protocol.elements.input_text import InputTextElement

__all__ = ["ImGuiInputTextRenderer"]


@final
class ImGuiInputTextRenderer(LeafRenderer[InputTextElement]):
    """Paint an InputTextElement via a per-paint InputTextRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the input (fires ValueChanged on edit)."""
        InputTextRenderer(self._factory.widget_state).render(self._elem)
