# pyright: reportMissingModuleSource=false
"""ImGuiImageRenderer — Renderer-Protocol adapter for ``ImageElement``.

Paints through a per-paint ``ImageRenderer`` (which uploads path-sourced images
through the factory's shared ``TextureCache`` and falls back to alt text).
``LeafRenderer`` adds the shared tooltip pass and records the leaf's rect; its
``measuring`` group spans the image plus any alt fallback the leaf paints, so the
recorded rect covers the whole leaf.
"""

from __future__ import annotations

from typing import final

from punt_lux.display.renderers.image_renderer import ImageRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.image import ImageElement

__all__ = ["ImGuiImageRenderer"]


@final
class ImGuiImageRenderer(LeafRenderer[ImageElement]):
    """Paint an ImageElement via ImageRenderer + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Upload and draw the image, or its alt-text fallback."""
        ImageRenderer(self._factory.texture_cache).render(self._elem)
