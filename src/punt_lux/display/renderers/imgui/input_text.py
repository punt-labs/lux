"""ImGuiInputTextRenderer — Renderer-Protocol adapter for ``InputTextElement``.

A leaf: paints through a per-paint ``InputTextRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
buffer and fires ``ValueChanged`` on a genuine edit (wrapped for D21 remote
dispatch). The paint adds the shared tooltip pass the factory owns. ``begin``
proceeds, ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.input_text_renderer import InputTextRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.input_text import InputTextElement

__all__ = ["ImGuiInputTextRenderer"]


@final
class ImGuiInputTextRenderer:
    """Paint an InputTextElement via a per-paint InputTextRenderer + tooltip."""

    _elem: InputTextElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: InputTextElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the input (fires ValueChanged on edit) + tooltip pass."""
        InputTextRenderer(self._factory.widget_state).render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
