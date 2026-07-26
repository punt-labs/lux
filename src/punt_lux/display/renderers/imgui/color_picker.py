"""ImGuiColorPickerRenderer — Renderer-Protocol adapter for ``ColorPickerElement``.

A leaf: paints through a per-paint ``ColorPickerRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
drag and fires ``ValueChanged`` on release (wrapped for D21 remote dispatch).
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.color_picker_renderer import ColorPickerRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.color_picker import ColorPickerElement

__all__ = ["ImGuiColorPickerRenderer"]


@final
class ImGuiColorPickerRenderer(LeafRenderer[ColorPickerElement]):
    """Paint a ColorPickerElement via a per-paint ColorPickerRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the picker (fires ValueChanged on release)."""
        ColorPickerRenderer(self._factory.widget_state).render(self._elem)
