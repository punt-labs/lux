"""RgbaColor — the ABC color-picker path's hex↔tuple↔hex value object.

A color is a hex string on the wire (``#RRGGBB`` / ``#RRGGBBAA``) and an RGBA
float tuple in the ImGui widget; ``RgbaColor`` owns that conversion as methods
on the data (PY-OO-5, PY-OO-7). It trusts a validated hex — a bad hex reaching
``from_hex`` is a construction bypass that raises rather than silently
whitening — and normalizes every tuple to arity 4 with finite ``[0, 1]``
channels, so tuple equality (the reconciliation carrier's only predicate) stays
well-defined.
"""

from __future__ import annotations

import math
from typing import Self, cast, final

__all__ = ["Rgba", "RgbaColor"]

# The Display-local RGBA float carrier: four channels in [0, 1], always arity 4.
type Rgba = tuple[float, float, float, float]


@final
class RgbaColor:
    """An immutable RGBA color, channels finite and clamped to ``[0, 1]``, arity 4."""

    _rgba: Rgba
    __slots__ = ("_rgba",)

    def __new__(cls, rgba: tuple[float, ...]) -> Self:
        self = super().__new__(cls)
        self._rgba = cls._normalize(rgba)
        return self

    @classmethod
    def from_hex(cls, hex_str: str) -> Self:
        """Return the color a well-formed ``#RRGGBB`` / ``#RRGGBBAA`` encodes.

        Total on a validated hex; a malformed hex is a construction bypass and
        raises ``ValueError`` (PY-EH-8) rather than whitening silently.
        """
        s = hex_str.lstrip("#")
        try:
            r = int(s[0:2], 16) / 255.0
            g = int(s[2:4], 16) / 255.0
            b = int(s[4:6], 16) / 255.0
            a = int(s[6:8], 16) / 255.0 if len(s) == 8 else 1.0
        except ValueError as exc:
            msg = f"not a well-formed hex color: {hex_str!r}"
            raise ValueError(msg) from exc
        if len(s) not in (6, 8):
            msg = f"hex color must be 6 or 8 digits, got {hex_str!r}"
            raise ValueError(msg)
        return cls((r, g, b, a))

    def to_hex(self, *, alpha: bool) -> str:
        """Return the 8-bit ``#RRGGBB`` (or ``#RRGGBBAA`` when ``alpha``) hex."""
        r, g, b, a = self._rgba
        body = f"#{self._channel(r):02X}{self._channel(g):02X}{self._channel(b):02X}"
        return f"{body}{self._channel(a):02X}" if alpha else body

    def as_tuple(self) -> Rgba:
        """Return the arity-4 RGBA tuple the ImGui widget consumes."""
        return self._rgba

    @classmethod
    def coerce(cls, stored: object) -> Rgba:
        """Return ``stored`` as an arity-4 RGBA tuple — the ``resolve`` return cast."""
        if not isinstance(stored, tuple):
            msg = f"color value must be a tuple, got {type(stored).__name__}"
            raise TypeError(msg)
        return cls._normalize(cast("tuple[float, ...]", stored))

    @staticmethod
    def _normalize(rgba: tuple[float, ...]) -> Rgba:
        """Return ``rgba`` as arity 4, each channel finite and clamped to ``[0, 1]``.

        A non-finite channel (``NaN`` / ``±inf``) is rejected (PY-EH-8): the
        reconciliation closes its echo window on tuple equality and ``NaN !=
        NaN`` would hold it open forever. Out-of-range channels are clamped, not
        rejected — ImGui can hand back a hair outside ``[0, 1]``.
        """
        if len(rgba) not in (3, 4):
            msg = f"color tuple must have 3 or 4 components, got {len(rgba)}"
            raise ValueError(msg)
        r, g, b = float(rgba[0]), float(rgba[1]), float(rgba[2])
        a = float(rgba[3]) if len(rgba) == 4 else 1.0
        # A NaN/±inf channel makes the sum non-finite (inf + -inf is NaN too).
        if not math.isfinite(r + g + b + a):
            msg = f"color channels must all be finite, got {rgba!r}"
            raise ValueError(msg)
        return (
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            max(0.0, min(1.0, a)),
        )

    @staticmethod
    def _channel(value: float) -> int:
        """Return one ``[0, 1]`` channel scaled to 8-bit ``0..255``."""
        return int(value * 255)
