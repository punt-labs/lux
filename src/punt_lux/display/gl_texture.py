# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Raw OpenGL texture upload/delete — the GL calls TextureCache delegates to."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


class GLTexture:
    """OpenGL texture primitives: upload a decoded image, delete by id.

    Kept apart from ``TextureCache`` so the caching/eviction policy has no
    direct OpenGL dependency of its own — every GL call in the display's
    texture path funnels through this one class.
    """

    @staticmethod
    def upload(img: PILImage) -> int:
        """Upload an RGBA PIL image as an OpenGL texture; return its texture id."""
        import OpenGL.GL as GL

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

    @staticmethod
    def delete(tex_id: int | None) -> None:
        """Delete one OpenGL texture by id; a no-op for a failure record's ``None``."""
        if tex_id is None:
            return
        import OpenGL.GL as GL

        GL.glDeleteTextures(1, [tex_id])
