# pyright: reportMissingModuleSource=false
"""ImGuiSeparatorRenderer — Renderer-Protocol adapter for ``SeparatorElement``.

Paints through a per-paint ``SeparatorRenderer`` (a bare ``imgui.separator()``)
plus the shared tooltip pass the factory owns. A separator is a leaf, so
``begin`` proceeds and ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.separator_renderer import SeparatorRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.separator import SeparatorElement

__all__ = ["ImGuiSeparatorRenderer"]


@final
class ImGuiSeparatorRenderer:
    """Paint a SeparatorElement via SeparatorRenderer + the shared tooltip pass."""

    _elem: SeparatorElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: SeparatorElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Draw the separator line and apply the shared tooltip pass."""
        SeparatorRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
