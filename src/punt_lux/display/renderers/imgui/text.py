"""ImGuiTextRenderer — Renderer-Protocol adapter for ``TextElement``.

Paints through a per-paint ``TextRenderer`` (style + color) plus the shared
tooltip pass the factory owns. Text is a leaf, so ``begin`` proceeds and
``end`` is a no-op.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.text_renderer import TextRenderer
from punt_lux.protocol.elements.text import TextElement

__all__ = ["ImGuiTextRenderer"]


@final
class ImGuiTextRenderer(LeafRenderer[TextElement]):
    """Paint a TextElement via ElementRenderer's TextRenderer + tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the text (style + color)."""
        TextRenderer().render(self._elem)
