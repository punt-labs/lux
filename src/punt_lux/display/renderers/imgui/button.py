"""ImGuiButtonRenderer — Renderer-Protocol adapter for ``ButtonElement``.

A leaf: paints through ``ElementRenderer``'s per-kind ``ButtonRenderer``
(the same instance whose click ``fire``s ``ButtonClicked``, wrapped for D21
remote dispatch) plus the shared ``apply_tooltip`` pass, reached via the
factory's narrow accessor. ``begin`` proceeds, ``end`` is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.button import ButtonElement

__all__ = ["ImGuiButtonRenderer"]


@final
class ImGuiButtonRenderer:
    """Paint a ButtonElement via ElementRenderer's ButtonRenderer + tooltip."""

    _elem: ButtonElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: ButtonElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the button (fires ButtonClicked on click) + tooltip pass."""
        er = self._factory.element_renderer
        er.button_renderer.render(self._elem)
        er.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
