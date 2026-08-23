"""LRU index over texture cache entries — the eviction policy TextureCache composes."""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from collections.abc import ItemsView, KeysView, ValuesView
from typing import Self

logger = logging.getLogger(__name__)

# 256 textures at a typical UI-image size (icons, avatars, small screenshots)
# is single-digit MiB of GPU memory — generous for a session's working set
# without letting an image-heavy agent run the display out of VRAM. Internal
# knob, not a public API: override with LUX_TEXTURE_CACHE_CAP for local tuning.
_DEFAULT_CAP = 256


class TextureLru:
    """Ordered, capped key→texture-id index with least-recently-used eviction.

    Composed into ``TextureCache`` rather than folded into it inline: the
    move-to-end-on-touch, evict-oldest-on-overflow discipline is a single
    reusable policy, and keeping it as its own class lets ``TextureCache``
    stay a coordinator over upload/decode instead of also owning ordering.
    """

    _order: OrderedDict[str, int | None]
    _cap: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._order = OrderedDict()
        self._cap = cls._cap_from_env()
        return self

    def __contains__(self, key: str) -> bool:
        return key in self._order

    def __getitem__(self, key: str) -> int | None:
        return self._order[key]

    def __len__(self) -> int:
        return len(self._order)

    def keys(self) -> KeysView[str]:
        return self._order.keys()

    def values(self) -> ValuesView[int | None]:
        return self._order.values()

    def items(self) -> ItemsView[str, int | None]:
        return self._order.items()

    def touch(self, key: str) -> None:
        """Mark *key* as most-recently-used without changing its value."""
        self._order.move_to_end(key)

    def remember(self, key: str, tex_id: int | None) -> int | None:
        """Insert *key* as most-recently-used; return an evicted texture id, if any.

        Returns the texture id of the entry evicted to stay within the cap, or
        ``None`` when nothing was evicted or the evicted entry was itself a
        failure record with no texture to delete.
        """
        self._order[key] = tex_id
        self._order.move_to_end(key)
        if len(self._order) <= self._cap:
            return None
        return self._order.popitem(last=False)[1]

    def clear(self) -> None:
        self._order.clear()

    @staticmethod
    def _cap_from_env() -> int:
        """Read ``LUX_TEXTURE_CACHE_CAP``, falling back to ``_DEFAULT_CAP`` if unset."""
        raw = os.environ.get("LUX_TEXTURE_CACHE_CAP", "")
        if not raw:
            return _DEFAULT_CAP
        return TextureLru._parse_cap(raw)

    @staticmethod
    def _parse_cap(raw: str) -> int:
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
