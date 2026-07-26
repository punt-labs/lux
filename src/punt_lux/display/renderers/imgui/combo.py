"""ImGuiComboRenderer — Renderer-Protocol adapter for ``ComboElement``.

A leaf: paints through a per-paint stateless ``ComboRenderer``, which reads
``elem.selected`` (the Hub-authoritative index) directly each frame. A genuine
user pick ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch.
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.combo_renderer import ComboRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.combo import ComboElement

__all__ = ["ImGuiComboRenderer"]


@final
class ImGuiComboRenderer(LeafRenderer[ComboElement]):
    """Paint a ComboElement via a per-paint ComboRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the combo (fires ValueChanged on pick)."""
        ComboRenderer().render(self._elem)
