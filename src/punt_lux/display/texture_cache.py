# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""OpenGL texture cache — maps image sources (path or inline data) to texture IDs."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from pathlib import Path
from typing import Self

from PIL import Image

from punt_lux.display.gl_texture import GLTexture
from punt_lux.display.texture_lru import TextureLru

logger = logging.getLogger(__name__)


class TextureCache:
    """Maps image sources to OpenGL texture IDs. Uploads on first access.

    A path-sourced image keys on its path; a data-sourced image keys on a
    content hash of its base64 payload (there is no path to key on). ``_lru``
    holds each key's resolution outcome once decided: an uploaded texture id, or
    ``None`` for a source that failed to load. A key present with ``None`` is the
    "known-failed" record, so a broken image is decoded and warned **once**, not
    every frame — the render loop retries neither the load nor the log.

    ``_lru`` caps entries under least-recently-used eviction (see
    ``TextureLru``): the least recently accessed key is dropped first, and its
    OpenGL texture is deleted at eviction time (a ``None`` failure record has
    nothing to delete). This bounds GPU memory for long-lived sessions that
    stream distinct images instead of letting the cache grow without limit for
    the process lifetime.
    """

    _lru: TextureLru
    _data_keys: dict[str, str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lru = TextureLru()
        self._data_keys = {}
        return self

    def __len__(self) -> int:
        """Return the number of live cache entries, for introspection/debugging."""
        return len(self._lru)

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading (and logging once) as needed."""
        if path in self._lru:
            self._lru.touch(path)
            return self._lru[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            GLTexture.delete(self._lru.remember(path, None))
            return None
        tex_id = self._create_texture(path)
        GLTexture.delete(self._lru.remember(path, tex_id))
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
        if key in self._lru:
            self._lru.touch(key)
            return self._lru[key]
        tex_id = self._create_texture_from_data(data)
        GLTexture.delete(self._lru.remember(key, tex_id))
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures and clear the caches."""
        for tex_id in self._lru.values():
            GLTexture.delete(tex_id)
        self._lru.clear()
        self._data_keys.clear()

    @staticmethod
    def _create_texture(path: str) -> int | None:
        """Load an image file and upload it as an OpenGL texture."""
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            logger.exception("Failed to load image: %s", path)
            return None
        return GLTexture.upload(img)

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
        return GLTexture.upload(img)
