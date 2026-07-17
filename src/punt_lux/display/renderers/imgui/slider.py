"""ImGuiSliderRenderer — Renderer-Protocol adapter for ``SliderElement``.

A leaf: paints through a per-paint ``SliderRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
drag and fires ``ValueChanged`` on release (wrapped for D21 remote dispatch). The
paint adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end``
is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.slider_renderer import SliderRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.slider import SliderElement

__all__ = ["ImGuiSliderRenderer"]


@final
class ImGuiSliderRenderer:
    """Paint a SliderElement via a per-paint SliderRenderer + tooltip."""

    _elem: SliderElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: SliderElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the slider (fires ValueChanged on release) + tooltip pass."""
        SliderRenderer(self._factory.widget_state).render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
