# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""OpenGL texture cache — maps image sources (path or inline data) to texture IDs."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Self

from PIL import Image

from punt_lux.display.data_key_memo import DataKeyMemo
from punt_lux.display.gl_texture import GLTexture
from punt_lux.display.texture_lru import TextureLru

logger = logging.getLogger(__name__)


class TextureCache:
    """Maps image sources to OpenGL texture IDs. Uploads on first access.

    A path-sourced image keys on its path; a data-sourced image keys on a
    content hash of its base64 payload, memoized by the composed
    ``DataKeyMemo`` (there is no path to key on). ``_lru`` holds each key's
    resolution outcome once decided: an uploaded texture id, or ``None`` for a
    source that failed to load. A key present with ``None`` is the
    "known-failed" record, so a broken image is decoded and warned **once**,
    not every frame — the render loop retries neither the load nor the log.

    ``_lru`` caps entries under least-recently-used eviction (see
    ``TextureLru``): the least recently accessed key is dropped first, and its
    OpenGL texture is deleted at eviction time (a ``None`` failure record has
    nothing to delete). ``_data_keys`` is coupled to that same eviction — when
    ``_lru`` evicts a data-sourced key, ``_settle`` tells the memo to forget it
    too — so both the textures and the payload memo are bounded by the same
    cap instead of growing for the process lifetime.
    """

    _lru: TextureLru
    _data_keys: DataKeyMemo

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lru = TextureLru()
        self._data_keys = DataKeyMemo()
        return self

    def __len__(self) -> int:
        """Return the number of live cache entries, for introspection/debugging."""
        return len(self._lru)

    def __repr__(self) -> str:
        return f"TextureCache(entries={len(self)})"

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading (and logging once) as needed."""
        if path in self._lru:
            self._lru.touch(path)
            return self._lru[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            self._settle(self._lru.remember(path, None))
            return None
        tex_id = self._create_texture(path)
        self._settle(self._lru.remember(path, tex_id))
        return tex_id

    def get_or_load_data(self, data: str) -> int | None:
        """Return a texture ID for a base64 image *data* blob, uploading if needed."""
        key = self._data_keys.key_for(data)
        if key in self._lru:
            self._lru.touch(key)
            return self._lru[key]
        tex_id = self._create_texture_from_data(data)
        self._settle(self._lru.remember(key, tex_id))
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures and clear the caches."""
        for tex_id in self._lru.values():
            GLTexture.delete(tex_id)
        self._lru.clear()
        self._data_keys.clear()

    def _settle(self, evicted: tuple[str, int | None] | None) -> None:
        """Delete an evicted texture and drop its data-key memo entry, if any."""
        if evicted is None:
            return
        key, tex_id = evicted
        GLTexture.delete(tex_id)
        self._data_keys.forget(key)

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
