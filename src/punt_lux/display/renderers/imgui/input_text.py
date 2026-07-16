"""ImGuiInputTextRenderer — Renderer-Protocol adapter for ``InputTextElement``.

A leaf: paints through ``ElementRenderer``'s per-scene ``InputTextRenderer``,
which reconciles the Hub value with the user's buffer via the shared
``ContinuousEditArbiter`` and fires ``ValueChanged`` on a genuine edit (wrapped
for D21 remote dispatch on the display side). The paint adds the shared
``apply_tooltip`` pass. ``begin`` proceeds, ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.input_text import InputTextElement

__all__ = ["ImGuiInputTextRenderer"]


@final
class ImGuiInputTextRenderer:
    """Paint an InputTextElement via ElementRenderer's InputTextRenderer + tooltip."""

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
        er = self._factory.element_renderer
        er.input_text_renderer.render(self._elem)
        er.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
