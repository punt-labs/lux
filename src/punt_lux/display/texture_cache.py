# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""OpenGL texture cache — maps image sources (path or inline data) to texture IDs."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Self

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)

# 256 textures at a typical UI-image size (icons, avatars, small screenshots)
# is single-digit MiB of GPU memory — generous for a session's working set
# without letting an image-heavy agent run the display out of VRAM. Internal
# knob, not a public API: override with LUX_TEXTURE_CACHE_CAP for local tuning.
_DEFAULT_CAP = 256


class TextureCache:
    """Maps image sources to OpenGL texture IDs. Uploads on first access.

    A path-sourced image keys on its path; a data-sourced image keys on a
    content hash of its base64 payload (there is no path to key on). ``_textures``
    holds each key's resolution outcome once decided: an uploaded texture id, or
    ``None`` for a source that failed to load. A key present with ``None`` is the
    "known-failed" record, so a broken image is decoded and warned **once**, not
    every frame — the render loop retries neither the load nor the log.

    ``_textures`` is capped at ``_cap`` entries under LRU eviction: the least
    recently accessed key is dropped first, and its OpenGL texture is deleted
    at eviction time (a ``None`` failure record has nothing to delete). This
    bounds GPU memory for long-lived sessions that stream distinct images
    instead of letting the cache grow without limit for the process lifetime.
    """

    _textures: OrderedDict[str, int | None]  # None marks a known-failed source
    _data_keys: dict[str, str]
    _cap: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._textures = OrderedDict()
        self._data_keys = {}
        self._cap = cls._cap_from_env()
        return self

    @staticmethod
    def _cap_from_env() -> int:
        """Read ``LUX_TEXTURE_CACHE_CAP``, falling back to ``_DEFAULT_CAP`` if unset."""
        raw = os.environ.get("LUX_TEXTURE_CACHE_CAP", "")
        if not raw:
            return _DEFAULT_CAP
        try:
            cap = int(raw)
        except ValueError:
            logger.warning(
                "LUX_TEXTURE_CACHE_CAP=%r is not an integer, defaulting to %d",
                raw,
                _DEFAULT_CAP,
            )
            return _DEFAULT_CAP
        if cap < 1:
            logger.warning(
                "LUX_TEXTURE_CACHE_CAP=%r must be >= 1, defaulting to %d",
                raw,
                _DEFAULT_CAP,
            )
            return _DEFAULT_CAP
        return cap

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading (and logging once) as needed."""
        if path in self._textures:
            self._textures.move_to_end(path)
            return self._textures[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            self._remember(path, None)
            return None
        tex_id = self._create_texture(path)
        self._remember(path, tex_id)
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
            self._textures.move_to_end(key)
            return self._textures[key]
        tex_id = self._create_texture_from_data(data)
        self._remember(key, tex_id)
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures and clear the caches."""
        for tex_id in self._textures.values():
            if tex_id is not None:
                self._delete_texture(tex_id)
        self._textures.clear()
        self._data_keys.clear()

    def _remember(self, key: str, tex_id: int | None) -> None:
        """Insert *key* as most-recently-used, evicting the LRU entry over cap."""
        self._textures[key] = tex_id
        self._textures.move_to_end(key)
        if len(self._textures) > self._cap:
            self._evict_lru()

    def _evict_lru(self) -> None:
        """Drop the least-recently-used entry, deleting its GPU texture if any."""
        _evicted_key, evicted_tex_id = self._textures.popitem(last=False)
        if evicted_tex_id is not None:
            self._delete_texture(evicted_tex_id)

    @staticmethod
    def _delete_texture(tex_id: int) -> None:
        """Delete one OpenGL texture by id."""
        import OpenGL.GL as GL

        GL.glDeleteTextures(1, [tex_id])

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
