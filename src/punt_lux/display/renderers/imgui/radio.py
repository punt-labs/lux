"""ImGuiRadioRenderer — Renderer-Protocol adapter for ``RadioElement``.

A leaf: paints through a per-paint stateless ``RadioRenderer``, which reads
``elem.selected`` (the Hub-authoritative index) directly each frame. A genuine
user pick ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch. The paint
adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end`` is a
no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.radio_renderer import RadioRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.radio import RadioElement

__all__ = ["ImGuiRadioRenderer"]


@final
class ImGuiRadioRenderer:
    """Paint a RadioElement via a per-paint RadioRenderer + tooltip."""

    _elem: RadioElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: RadioElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the radio group (fires ValueChanged on pick) + tooltip pass."""
        RadioRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
