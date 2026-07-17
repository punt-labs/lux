"""ImGuiColorPickerRenderer — Renderer-Protocol adapter for ``ColorPickerElement``.

A leaf: paints through a per-paint ``ColorPickerRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
drag and fires ``ValueChanged`` on release (wrapped for D21 remote dispatch). The
paint adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end``
is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.color_picker_renderer import ColorPickerRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.color_picker import ColorPickerElement

__all__ = ["ImGuiColorPickerRenderer"]


@final
class ImGuiColorPickerRenderer:
    """Paint a ColorPickerElement via a per-paint ColorPickerRenderer + tooltip."""

    _elem: ColorPickerElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: ColorPickerElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the picker (fires ValueChanged on release) + tooltip pass."""
        ColorPickerRenderer(self._factory.widget_state).render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
