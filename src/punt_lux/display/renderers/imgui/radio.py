# pyright: reportMissingModuleSource=false
"""ImGuiRadioRenderer — Renderer-Protocol adapter for ``RadioElement``.

A leaf: paints through a per-paint stateless ``RadioRenderer``, which reads
``elem.selected`` (the Hub-authoritative index) directly each frame. A genuine
user pick ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch.
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
A radio group paints one item per option, so the widget is wrapped in an ImGui
group; the captured rect then spans every button.
"""

from __future__ import annotations

from typing import final

from imgui_bundle import imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.radio_renderer import RadioRenderer
from punt_lux.protocol.elements.radio import RadioElement

__all__ = ["ImGuiRadioRenderer"]


@final
class ImGuiRadioRenderer(LeafRenderer[RadioElement]):
    """Paint a RadioElement via a per-paint RadioRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the radio group, grouped so its rect spans every button."""
        imgui.begin_group()
        RadioRenderer().render(self._elem)
        imgui.end_group()
