# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ImageElement — uploads via TextureCache, falls back to alt text."""

from __future__ import annotations

from typing import Self

from imgui_bundle import ImVec2, imgui

from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.image import ImageElement

__all__ = ["ImageRenderer"]


# Image default size — preserves pre-migration behaviour of the original renderer.
_DEFAULT_WIDTH = 200
_DEFAULT_HEIGHT = 150


class ImageRenderer:
    """Render an ImageElement using a TextureCache for path-based images."""

    _texture_cache: TextureCache

    def __new__(cls, texture_cache: TextureCache) -> Self:
        self = super().__new__(cls)
        self._texture_cache = texture_cache
        return self

    def render(self, elem: ImageElement) -> None:
        width = elem.width if elem.width is not None else _DEFAULT_WIDTH
        height = elem.height if elem.height is not None else _DEFAULT_HEIGHT
        tex_id = self._texture_cache.get_or_load(elem.path) if elem.path else None
        if tex_id is not None:
            imgui.image(imgui.ImTextureRef(tex_id), ImVec2(width, height))
            return
        alt = elem.alt or elem.path or "(image)"
        imgui.text(f"[{alt}]")
