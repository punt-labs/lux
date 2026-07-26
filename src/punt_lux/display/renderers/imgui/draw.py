"""ImGuiDrawRenderer — Renderer-Protocol adapter for ``DrawElement``.

A display-only leaf that paints a 2D canvas: the background fill and the typed
command replay. This migration moves *where* the paint lives (the ABC leaf path,
fork-don't-mix) and *who* validates a command (the Hub, via
``DrawCommandDecoder``), not how the commands are drawn — the replay engine is
the existing ``DrawElementRenderer``, composed here rather than reimplemented.
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.draw_element_renderer import DrawElementRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.draw import DrawElement

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory

__all__ = ["ImGuiDrawRenderer"]


@final
class ImGuiDrawRenderer(LeafRenderer[DrawElement]):
    """Paint a DrawElement's canvas via the command-replay engine + tooltip pass."""

    _painter: DrawElementRenderer
    __slots__ = ("_painter",)

    def __new__(cls, elem: DrawElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls, elem, factory)
        self._painter = DrawElementRenderer()
        return self

    def _paint_widget(self) -> None:
        """Replay the element's commands onto the ImGui draw list."""
        self._painter.render(self._elem)
