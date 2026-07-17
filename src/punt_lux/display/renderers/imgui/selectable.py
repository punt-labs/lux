"""ImGuiSelectableRenderer — Renderer-Protocol adapter for ``SelectableElement``.

A leaf: paints through a per-paint stateless ``SelectableRenderer``, which reads
``elem.selected`` (the Hub-authoritative state) directly each frame. A genuine
user click ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch. The paint
adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end`` is a
no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.selectable_renderer import SelectableRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.selectable import SelectableElement

__all__ = ["ImGuiSelectableRenderer"]


@final
class ImGuiSelectableRenderer:
    """Paint a SelectableElement via a per-paint SelectableRenderer + tooltip."""

    _elem: SelectableElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: SelectableElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the selectable (fires ValueChanged on click) + tooltip pass."""
        SelectableRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
