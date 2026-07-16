"""ImGuiColorPickerRenderer — Renderer-Protocol adapter for ``ColorPickerElement``.

A leaf: paints through ``ElementRenderer``'s per-scene ``ColorPickerRenderer``,
which reconciles the Hub value with the user's drag via the shared
``ContinuousEditArbiter`` and fires ``ValueChanged`` on release (wrapped for D21
remote dispatch on the display side). The paint adds the shared
``apply_tooltip`` pass. ``begin`` proceeds, ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.color_picker import ColorPickerElement

__all__ = ["ImGuiColorPickerRenderer"]


@final
class ImGuiColorPickerRenderer:
    """Paint a ColorPickerElement via ElementRenderer's per-scene renderer + tooltip."""

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
        er = self._factory.element_renderer
        er.color_picker_renderer.render(self._elem)
        er.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
