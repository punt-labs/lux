"""ImGuiSelectableRenderer — Renderer-Protocol adapter for ``SelectableElement``.

A leaf: paints through a per-paint stateless ``SelectableRenderer``, which reads
``elem.selected`` (the Hub-authoritative state) directly each frame. A genuine
user click ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch.
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.selectable_renderer import SelectableRenderer
from punt_lux.protocol.elements.selectable import SelectableElement

__all__ = ["ImGuiSelectableRenderer"]


@final
class ImGuiSelectableRenderer(LeafRenderer[SelectableElement]):
    """Paint a SelectableElement via a per-paint SelectableRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the selectable (fires ValueChanged on click)."""
        SelectableRenderer().render(self._elem)
