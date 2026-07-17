"""ImGuiInputNumberRenderer — Renderer-Protocol adapter for ``InputNumberElement``.

A leaf: paints through a per-paint ``InputNumberRenderer`` built on the factory's
per-scene ``WidgetState`` (its ``ContinuousEditArbiter`` buffer lives keyed in
that state, not on the renderer). It reconciles the Hub value with the user's
edit and fires ``ValueChanged`` on commit (wrapped for D21 remote dispatch). The
paint adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end``
is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.input_number_renderer import InputNumberRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.input_number import InputNumberElement

__all__ = ["ImGuiInputNumberRenderer"]


@final
class ImGuiInputNumberRenderer:
    """Paint an InputNumberElement via a per-paint InputNumberRenderer + tooltip."""

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
        InputNumberRenderer(self._factory.widget_state).render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
