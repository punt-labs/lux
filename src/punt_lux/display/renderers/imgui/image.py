# pyright: reportMissingModuleSource=false
"""ImGuiImageRenderer — Renderer-Protocol adapter for ``ImageElement``.

Paints through a per-paint ``ImageRenderer`` (which uploads path-sourced images
through the factory's shared ``TextureCache`` and falls back to alt text).
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
The image plus its alt fallback can paint more than one item, so the widget is
wrapped in an ImGui group; the captured rect then spans the whole leaf.
"""

from __future__ import annotations

from typing import final

from imgui_bundle import imgui

from punt_lux.display.renderers.image_renderer import ImageRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.image import ImageElement

__all__ = ["ImGuiImageRenderer"]


@final
class ImGuiImageRenderer(LeafRenderer[ImageElement]):
    """Paint an ImageElement via ImageRenderer + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Upload/draw the image (texture or alt fallback), grouped as one rect."""
        imgui.begin_group()
        ImageRenderer(self._factory.texture_cache).render(self._elem)
        imgui.end_group()
