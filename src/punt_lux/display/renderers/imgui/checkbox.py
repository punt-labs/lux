"""ImGuiCheckboxRenderer — Renderer-Protocol adapter for ``CheckboxElement``.

A leaf: paints through a per-paint stateless ``CheckboxRenderer``, which reads
``elem.value`` (the Hub-authoritative state) directly each frame. A genuine user
toggle ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch. The paint
adds the shared tooltip pass the factory owns. ``begin`` proceeds, ``end`` is a
no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.renderers.checkbox_renderer import CheckboxRenderer

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.checkbox import CheckboxElement

__all__ = ["ImGuiCheckboxRenderer"]


@final
class ImGuiCheckboxRenderer:
    """Paint a CheckboxElement via a per-paint CheckboxRenderer + tooltip."""

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
        CheckboxRenderer().render(self._elem)
        self._factory.apply_tooltip(self._elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
