# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""OpenGL texture cache — maps file paths to texture IDs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Self

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class TextureCache:
    """Maps file paths to OpenGL texture IDs. Uploads on first access."""

    _textures: dict[str, int]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._textures = {}
        return self

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading if needed."""
        if path in self._textures:
            return self._textures[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            return None
        tex_id = self._create_texture(path)
        if tex_id is not None:
            self._textures[path] = tex_id
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures."""
        import OpenGL.GL as GL

        for tex_id in self._textures.values():
            GL.glDeleteTextures(1, [tex_id])
        self._textures.clear()

    @staticmethod
    def _create_texture(path: str) -> int | None:
        """Load an image file and upload it as an OpenGL texture."""
        import OpenGL.GL as GL

        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            logger.exception("Failed to load image: %s", path)
            return None

        data = np.array(img, dtype=np.uint8)
        h, w = data.shape[:2]

        tex_id: int = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D,
            0,
            GL.GL_RGBA,
            w,
            h,
            0,
            GL.GL_RGBA,
            GL.GL_UNSIGNED_BYTE,
            data,
        )
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        return int(tex_id)
