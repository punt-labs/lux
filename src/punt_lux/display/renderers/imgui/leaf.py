# pyright: reportMissingModuleSource=false
"""LeafRenderer — the shared base for every leaf ImGui adapter.

A leaf paints one widget and has no children, so ``begin`` proceeds, ``end`` is a
no-op, and ``paint`` is a fixed template: draw the widget, record its painted
geometry, then run the shared tooltip pass. Recording lives here, at the one
point both render paths reach — ``elem.render()`` for top-level and ABC-nested
elements, and ``_render_via_factory`` for an ABC leaf inside a legacy container —
so no leaf kind can be added without its geometry being captured.

The item rect is read before the tooltip pass, so ``get_item_rect`` bounds the
widget rather than a tooltip window a hover might have opened. A leaf whose widget
paints several items (markdown lines, image plus alt text) wraps its
``_paint_widget`` in an ImGui group so the rect spans the whole leaf.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.element_abc import Element as AbcElement

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol import Element

__all__ = ["LeafRenderer"]


class LeafRenderer[E: AbcElement](ABC):
    """Base leaf adapter: fixed begin/paint/end template over a widget hook."""

    _elem: E
    _factory: ImGuiRendererFactory
    __slots__ = ("_elem", "_factory")

    def __new__(cls, elem: E, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Draw the widget, record its rect, then apply the shared tooltip pass."""
        self._paint_widget()
        self._factory.geometry.record_item(self._elem.id)
        self._factory.apply_tooltip(cast("Element", self._elem))

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened

    @abstractmethod
    def _paint_widget(self) -> None:
        """Draw this leaf's own widget. Each kind implements exactly this."""
