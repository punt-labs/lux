"""Hex colour parsers — return ``None`` on bad input with a warning.

PY-TS-14 OK on ``| None``: absence is the documented contract; callers
guard the colour push so ImGui's theme default renders on malformed
input.  Always-opaque-white fallback regressed text rendering.
"""

from __future__ import annotations

import logging

__all__ = ["parse_hex_color", "parse_rgba"]

_log = logging.getLogger(__name__)

_WHITE_RGBA: tuple[int, int, int, int] = (255, 255, 255, 255)


def _channels(hex_str: str) -> tuple[int, int, int, int] | None:
    """Return ``(r, g, b, a)`` 0..255 or ``None`` on malformed input; log on failure."""
    s = hex_str.lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        if len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except ValueError:
        _log.warning("invalid hex color %r — caller will fall back", hex_str)
        return None
    _log.warning("hex color %r not 6/8 hex digits — caller will fall back", hex_str)
    return None


def parse_hex_color(hex_str: str) -> tuple[float, float, float, float] | None:
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to floats 0..1, or ``None`` if invalid."""
    rgba = _channels(hex_str)
    if rgba is None:
        return None
    r, g, b, a = rgba
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def parse_rgba(hex_str: str) -> tuple[int, int, int, int]:
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to ``(r, g, b, a)`` ints 0..255."""
    return _channels(hex_str) or _WHITE_RGBA
