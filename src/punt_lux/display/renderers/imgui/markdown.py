# pyright: reportMissingModuleSource=false
"""ImGuiMarkdownRenderer — Renderer-Protocol adapter for ``MarkdownElement``.

Paints through a per-paint ``MarkdownRenderer`` (which owns the ``imgui_md``
graceful-degradation fallback) plus the shared tooltip pass the factory owns.
Markdown is a leaf, so ``begin`` proceeds and ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.markdown_renderer import MarkdownRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["ImGuiMarkdownRenderer"]


@final
class ImGuiMarkdownRenderer:
    """Paint a MarkdownElement via MarkdownRenderer + the shared tooltip pass."""

    _elem: MarkdownElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: MarkdownElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Render the markdown block and apply the shared tooltip pass."""
        MarkdownRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
