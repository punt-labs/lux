"""ImGuiSliderRenderer — Renderer-Protocol adapter for ``SliderElement``.

A leaf: paints through a per-paint ``SliderRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
drag and fires ``ValueChanged`` on release (wrapped for D21 remote dispatch).
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.slider_renderer import SliderRenderer
from punt_lux.protocol.elements.slider import SliderElement

__all__ = ["ImGuiSliderRenderer"]


@final
class ImGuiSliderRenderer(LeafRenderer[SliderElement]):
    """Paint a SliderElement via a per-paint SliderRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the slider (fires ValueChanged on release)."""
        SliderRenderer(self._factory.widget_state).render(self._elem)
