# pyright: reportMissingModuleSource=false
"""ImGuiMarkdownRenderer — Renderer-Protocol adapter for ``MarkdownElement``.

Paints through a per-paint ``MarkdownRenderer`` (which owns the ``imgui_md``
graceful-degradation fallback). ``LeafRenderer`` adds the shared tooltip pass and
records the leaf's rect; its ``measuring`` group spans every line the block
paints, so the recorded rect covers the whole block, not just its last line.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.markdown_renderer import MarkdownRenderer
from punt_lux.protocol.elements.markdown import MarkdownElement

__all__ = ["ImGuiMarkdownRenderer"]


@final
class ImGuiMarkdownRenderer(LeafRenderer[MarkdownElement]):
    """Paint a MarkdownElement via MarkdownRenderer + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Render the markdown block."""
        MarkdownRenderer().render(self._elem)
