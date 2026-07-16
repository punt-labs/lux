"""ImGuiInputNumberRenderer — Renderer-Protocol adapter for ``InputNumberElement``.

A leaf: paints through ``ElementRenderer``'s per-scene ``InputNumberRenderer``,
which reconciles the Hub value with the user's edit via the shared
``ContinuousEditArbiter`` and fires ``ValueChanged`` on commit (wrapped for D21
remote dispatch on the display side). The paint adds the shared ``apply_tooltip``
pass. ``begin`` proceeds, ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.input_number import InputNumberElement

__all__ = ["ImGuiInputNumberRenderer"]


@final
class ImGuiInputNumberRenderer:
    """Paint an InputNumberElement via ElementRenderer's renderer + tooltip."""

    _elem: InputNumberElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: InputNumberElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the input (fires ValueChanged on commit) + tooltip pass."""
        er = self._factory.element_renderer
        er.input_number_renderer.render(self._elem)
        er.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
