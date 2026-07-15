"""RgbaColor — the ABC color-picker path's hex↔tuple↔hex value object.

A color is a hex string on the wire (``#RRGGBB`` / ``#RRGGBBAA``) and an RGBA
float tuple in the ImGui widget. ``RgbaColor`` owns that conversion as methods on
the data (PY-OO-5, PY-OO-7) — the color analog of ``Point2`` composition
(PY-IC-1) — rather than free functions beside the renderer.

It is *not* ``_color.py``'s ``parse_hex_color`` / ``parse_rgba`` reheated: those
stay for the still-legacy ``text`` / ``spinner`` color-styling paths and fall
back on malformed input; ``RgbaColor`` is the ABC path's own value type and
trusts a validated hex (``ColorPickerElement.validate`` rejects malformed input
before render), so a bad hex reaching ``from_hex`` is a construction bypass that
raises rather than silently whitening.

The tuple is always arity 4 (alpha defaults to ``1.0`` when a 6-digit hex has
none), so tuple equality — the reconciliation carrier's only predicate — is
well-defined: a 3-tuple never equals a 4-tuple.
"""

from __future__ import annotations

from typing import Self, cast, final

__all__ = ["Rgba", "RgbaColor"]

# The Display-local RGBA float carrier: four channels in [0, 1], always arity 4.
type Rgba = tuple[float, float, float, float]


@final
class RgbaColor:
    """An immutable RGBA color in ``[0, 1]``, the hex↔tuple seam's value type."""

    _rgba: Rgba
    __slots__ = ("_rgba",)

    def __new__(cls, rgba: tuple[float, ...]) -> Self:
        self = super().__new__(cls)
        self._rgba = cls._normalize(rgba)
        return self

    @classmethod
    def from_hex(cls, hex_str: str) -> Self:
        """Return the color a well-formed ``#RRGGBB`` / ``#RRGGBBAA`` encodes.

        Total on a validated hex — ``ColorPickerElement.validate`` guarantees the
        ``#`` + 6/8-hex-digit shape before render, so the ``int(..., 16)`` parses
        never fault on the render path. A malformed hex is a construction bypass
        and raises ``ValueError`` (PY-EH-8) rather than whitening silently.
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
        """Return the 8-bit ``#RRGGBB`` (or ``#RRGGBBAA``) hex, channels clamped.

        The alpha channel is dropped from the wire form when ``alpha`` is False,
        so an RGB picker's committed value stays ``#RRGGBB`` even though the
        carrier keeps a fourth component.
        """
        r, g, b, a = self._rgba
        body = f"#{self._channel(r):02X}{self._channel(g):02X}{self._channel(b):02X}"
        return f"{body}{self._channel(a):02X}" if alpha else body

    def as_tuple(self) -> Rgba:
        """Return the arity-4 RGBA tuple the ImGui widget consumes."""
        return self._rgba

    @classmethod
    def coerce(cls, stored: object) -> Rgba:
        """Return ``stored`` as an arity-4 RGBA tuple — the ``resolve`` return cast.

        The color analog of ``float(committed)`` in ``SliderArbiter.resolve``:
        the committed slot holds a tuple, and this guarantees arity 4 before the
        renderer hands it back to ImGui.
        """
        if not isinstance(stored, tuple):
            msg = f"color value must be a tuple, got {type(stored).__name__}"
            raise TypeError(msg)
        return cls._normalize(cast("tuple[float, ...]", stored))

    @staticmethod
    def _normalize(rgba: tuple[float, ...]) -> Rgba:
        """Return ``rgba`` as arity 4, padding a missing alpha to opaque ``1.0``."""
        if len(rgba) == 4:
            return (float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
        if len(rgba) == 3:
            return (float(rgba[0]), float(rgba[1]), float(rgba[2]), 1.0)
        msg = f"color tuple must have 3 or 4 components, got {len(rgba)}"
        raise ValueError(msg)

    @staticmethod
    def _channel(value: float) -> int:
        """Return one channel clamped to ``[0, 1]`` and scaled to 8-bit ``0..255``."""
        return int(max(0.0, min(1.0, value)) * 255)
