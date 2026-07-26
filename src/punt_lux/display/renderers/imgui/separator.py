"""ImGuiSeparatorRenderer — Renderer-Protocol adapter for ``SeparatorElement``.

Paints through a per-paint ``SeparatorRenderer`` (a bare ``imgui.separator()``).
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.separator_renderer import SeparatorRenderer
from punt_lux.protocol.elements.separator import SeparatorElement

__all__ = ["ImGuiSeparatorRenderer"]


@final
class ImGuiSeparatorRenderer(LeafRenderer[SeparatorElement]):
    """Paint a SeparatorElement via SeparatorRenderer + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Draw the separator line."""
        SeparatorRenderer().render(self._elem)
