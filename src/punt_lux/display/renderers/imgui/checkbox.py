"""ImGuiCheckboxRenderer — Renderer-Protocol adapter for ``CheckboxElement``.

A leaf: paints through a per-paint stateless ``CheckboxRenderer``, which reads
``elem.value`` (the Hub-authoritative state) directly each frame. A genuine user
toggle ``fire``s ``ValueChanged``, wrapped for D21 remote dispatch. ``LeafRenderer``
adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.checkbox_renderer import CheckboxRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.checkbox import CheckboxElement

__all__ = ["ImGuiCheckboxRenderer"]


@final
class ImGuiCheckboxRenderer(LeafRenderer[CheckboxElement]):
    """Paint a CheckboxElement via a per-paint CheckboxRenderer + tooltip."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Paint the checkbox (fires ValueChanged on toggle)."""
        CheckboxRenderer().render(self._elem)
