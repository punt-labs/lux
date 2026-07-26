"""ImGuiSpinnerRenderer — Renderer-Protocol adapter for ``SpinnerElement``.

Paints through a per-paint ``SpinnerRenderer`` (which owns the ``imspinner``
graceful-degradation fallback). ``LeafRenderer`` adds the shared tooltip pass and
the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.spinner_renderer import SpinnerRenderer
from punt_lux.protocol.elements.spinner import SpinnerElement

__all__ = ["ImGuiSpinnerRenderer"]


@final
class ImGuiSpinnerRenderer(LeafRenderer[SpinnerElement]):
    """Paint a SpinnerElement via SpinnerRenderer + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Render the spinner."""
        SpinnerRenderer().render(self._elem)
