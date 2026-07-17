"""ImGuiTextRenderer — Renderer-Protocol adapter for ``TextElement``.

Paints through a per-paint ``TextRenderer`` (style + color) plus the shared
tooltip pass the factory owns. Text is a leaf, so ``begin`` proceeds and
``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.text_renderer import TextRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.text import TextElement

__all__ = ["ImGuiTextRenderer"]


@final
class ImGuiTextRenderer:
    """Paint a TextElement via ElementRenderer's TextRenderer + tooltip pass."""

    _elem: TextElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: TextElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the text (style + color) and apply the shared tooltip pass."""
        TextRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
