# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ImageElement — uploads via TextureCache, falls back to alt text."""

from __future__ import annotations

import logging
from typing import Self

from imgui_bundle import ImVec2, imgui

from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.image_source import DataImage

__all__ = ["ImageRenderer"]

logger = logging.getLogger(__name__)


# Image default size — preserves pre-migration behaviour of the original renderer.
_DEFAULT_WIDTH = 200
_DEFAULT_HEIGHT = 150


class ImageRenderer:
    """Render an ImageElement, uploading path- or data-sourced pixels to a texture."""

    _texture_cache: TextureCache

    def __new__(cls, texture_cache: TextureCache) -> Self:
        self = super().__new__(cls)
        self._texture_cache = texture_cache
        return self

    def render(self, elem: ImageElement) -> None:
        """Paint the image, or its alt text when no texture is available."""
        width = elem.width if elem.width is not None else _DEFAULT_WIDTH
        height = elem.height if elem.height is not None else _DEFAULT_HEIGHT
        tex_id = self._resolve_texture(elem)
        if tex_id is not None:
            imgui.image(imgui.ImTextureRef(tex_id), ImVec2(width, height))
            return
        alt = elem.alt or elem.path or "(image)"
        imgui.text(f"[{alt}]")

    def _resolve_texture(self, elem: ImageElement) -> int | None:
        """Return the element's texture id, or ``None`` to fall back to alt text.

        The source dispatches to the right cache leg (path vs data). A data blob
        that will not decode is not a crash: the cache returns ``None``, and this
        logs a warning naming the element so the frame survives on alt text.
        """
        tex_id = elem.source.load_texture(self._texture_cache)
        if tex_id is None and isinstance(elem.source, DataImage):
            logger.warning(
                "image %s: inline data did not decode to an image; showing alt text",
                elem.id,
            )
        return tex_id
