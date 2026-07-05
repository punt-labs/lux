"""ImGuiCheckboxRenderer — Renderer-Protocol adapter for ``CheckboxElement``.

A leaf: paints through ``ElementRenderer``'s per-kind ``CheckboxRenderer``
(the same instance the ``widget_state`` setter re-threads per scene, so it
reads the current scene's state; its toggle ``fire``s ``ValueChanged``,
wrapped for D21 remote dispatch) plus the shared ``apply_tooltip`` pass,
reached via the factory's narrow accessor. ``begin`` proceeds, ``end`` is a
no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.checkbox import CheckboxElement

__all__ = ["ImGuiCheckboxRenderer"]


@final
class ImGuiCheckboxRenderer:
    """Paint a CheckboxElement via ElementRenderer's CheckboxRenderer + tooltip."""

    _elem: CheckboxElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: CheckboxElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Paint the checkbox (fires ValueChanged on toggle) + tooltip pass."""
        er = self._factory.element_renderer
        er.checkbox_renderer.render(self._elem)
        er.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
