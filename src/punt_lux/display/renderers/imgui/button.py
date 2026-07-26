"""ImGuiButtonRenderer — Renderer-Protocol adapter for ``ButtonElement``.

A leaf: paints through a per-paint ``ButtonRenderer`` (whose click ``fire``s
``ButtonClicked``, wrapped for D21 remote dispatch). ``LeafRenderer`` adds the
shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.button_renderer import ButtonRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.button import ButtonElement

__all__ = ["ImGuiButtonRenderer"]


@final
class ImGuiButtonRenderer(LeafRenderer[ButtonElement]):
    """Paint a ButtonElement via a per-paint ButtonRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the button (fires ButtonClicked on click)."""
        ButtonRenderer().render(self._elem)
