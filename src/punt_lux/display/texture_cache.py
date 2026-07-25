# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""OpenGL texture cache — maps image sources (path or inline data) to texture IDs."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Self

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)


class TextureCache:
    """Maps image sources to OpenGL texture IDs. Uploads on first access.

    A path-sourced image keys on its path; a data-sourced image keys on a
    content hash of its base64 payload (there is no path to key on). ``_textures``
    holds each key's resolution outcome once decided: an uploaded texture id, or
    ``None`` for a source that failed to load. A key present with ``None`` is the
    "known-failed" record, so a broken image is decoded and warned **once**, not
    every frame — the render loop retries neither the load nor the log.
    """

    _textures: dict[str, int | None]  # None marks a known-failed source
    _data_keys: dict[str, str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._textures = {}
        self._data_keys = {}
        return self

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading (and logging once) as needed."""
        if path in self._textures:
            return self._textures[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            self._textures[path] = None
            return None
        self._textures[path] = tex_id = self._create_texture(path)
        return tex_id

    def get_or_load_data(self, data: str) -> int | None:
        """Return a texture ID for a base64 image *data* blob, uploading if needed.

        Keyed by a content hash of the payload, since a data-sourced image has
        no path. The renderer asks for the same payload every frame, so the
        payload→key mapping is memoized in ``_data_keys``: only the first sight
        of a payload pays the SHA-256, and a persistent element's repeated loads
        are an amortized O(1) dict hit (Python caches a str's hash). Malformed
        base64 or bytes that are not a decodable image yield ``None`` and the key
        is remembered, so a broken payload is decoded and logged exactly once —
        the caller degrades to alt text and the render loop survives.
        """
        if (key := self._data_keys.get(data)) is None:
            key = self._data_keys[data] = (
                f"data:{hashlib.sha256(data.encode()).hexdigest()}"
            )
        if key in self._textures:
            return self._textures[key]
        self._textures[key] = tex_id = self._create_texture_from_data(data)
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures and clear the caches."""
        import OpenGL.GL as GL

        for tex_id in self._textures.values():
            if tex_id is not None:
                GL.glDeleteTextures(1, [tex_id])
        self._textures.clear()
        self._data_keys.clear()

    @staticmethod
    def _create_texture(path: str) -> int | None:
        """Load an image file and upload it as an OpenGL texture."""
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            logger.exception("Failed to load image: %s", path)
            return None
        return TextureCache._upload(img)

    @staticmethod
    def _create_texture_from_data(data: str) -> int | None:
        """Decode a base64 image blob and upload it; ``None`` on malformed input.

        The base64 decode and the image parse are the untrusted boundary — bad
        base64 (``binascii.Error``, a ``ValueError``) or non-image bytes
        (``PIL.UnidentifiedImageError``, an ``OSError``) are caught here so a
        malformed data URL degrades to alt text instead of faulting the frame.
        """
        try:
            raw = base64.b64decode(data, validate=True)
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
        except (ValueError, OSError) as exc:
            logger.warning(
                "Failed to decode inline image data (%d base64 chars): %s",
                len(data),
                exc,
            )
            return None
        return TextureCache._upload(img)

    @staticmethod
    def _upload(img: PILImage) -> int:
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
