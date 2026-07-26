# pyright: reportMissingModuleSource=false
"""LeafRenderer — the shared base for every leaf ImGui adapter.

A leaf paints one widget and has no children, so ``begin`` proceeds, ``end`` is a
no-op, and ``paint`` is a fixed template: paint the widget and its tooltip inside
the geometry ``measuring`` group, which records the leaf's rect over the whole
paint when the group closes (see ``GeometryCapture.measuring`` for why the group
bounds a multi-item leaf and outlasts its tooltip). Recording lives here, the one
point both render paths reach — ``elem.render()`` for top-level and ABC-nested
elements, and ``_render_via_factory`` for an ABC leaf inside a legacy container —
so no leaf kind can be added without its geometry being captured.
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
        """Paint the widget and tooltip inside the group that records the rect."""
        with self._factory.geometry.measuring(self._elem.id):
            self._paint_widget()
            self._factory.apply_tooltip(cast("Element", self._elem))

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened

    @abstractmethod
    def _paint_widget(self) -> None:
        """Draw this leaf's own widget. Each kind implements exactly this."""
