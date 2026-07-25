# pyright: reportMissingModuleSource=false
"""ImGuiSpinnerRenderer — Renderer-Protocol adapter for ``SpinnerElement``.

Paints through a per-paint ``SpinnerRenderer`` (which owns the ``imspinner``
graceful-degradation fallback) plus the shared tooltip pass the factory owns.
A spinner is a leaf, so ``begin`` proceeds and ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.spinner_renderer import SpinnerRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.spinner import SpinnerElement

__all__ = ["ImGuiSpinnerRenderer"]


@final
class ImGuiSpinnerRenderer:
    """Paint a SpinnerElement via SpinnerRenderer + the shared tooltip pass."""

    _elem: SpinnerElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: SpinnerElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Render the spinner and apply the shared tooltip pass."""
        SpinnerRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
