"""JsonEncoderFactory — top-level wire encoder dispatching by element type.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 4 and §3: the io-model
outbound dispatcher. Stateless — one instance shared across the
process; each ``encode(elem)`` call routes to the per-kind encoder for
``type(elem)``.

PR 3 ships Text-only dispatch. PRs 4-11 add Button, Panel, Dialog, and
the remaining 19 kinds as each family migrates from the PR-2
``ElementCodec`` path to the io-model.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextEncoder

__all__ = ["JsonEncoderFactory"]


class JsonEncoderFactory:
    """Dispatch elements to per-kind encoders by their concrete type."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: object) -> dict[str, object]:
        """Dispatch by ``type(elem)`` to the per-kind encoder.

        PR 3 only handles ``TextElement``. PR 4 adds ``ButtonElement``,
        ``PanelElement``, ``DialogElement`` cases here.
        """
        if isinstance(elem, TextElement):
            return JsonTextEncoder().encode(elem)
        msg = f"JsonEncoderFactory has no encoder for {type(elem).__name__}"
        raise TypeError(msg)
