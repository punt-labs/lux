"""Hex colour parsers — opaque-white fallback with a warning on bad input.

Malformed input never crashes the frame; PY-EH-8 demands the fallback be
logged so silent mis-rendering is visible.
"""

from __future__ import annotations

import logging

__all__ = ["parse_hex_color", "parse_rgba"]

_log = logging.getLogger(__name__)

_WHITE_FLOAT: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
_WHITE_RGBA: tuple[int, int, int, int] = (255, 255, 255, 255)


def _channels(hex_str: str) -> tuple[int, int, int, int] | None:
    """Return (r, g, b, a) 0..255 or None on malformed input; log on failure."""
    s = hex_str.lstrip("#")
    try:
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        if len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except ValueError:
        _log.warning("invalid hex color %r — falling back to white", hex_str)
        return None
    _log.warning("hex color %r not 6/8 hex digits — falling back to white", hex_str)
    return None


def parse_hex_color(hex_str: str) -> tuple[float, float, float, float]:
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to ``(r, g, b, a)`` floats 0..1."""
    rgba = _channels(hex_str)
    if rgba is None:
        return _WHITE_FLOAT
    r, g, b, a = rgba
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def parse_rgba(hex_str: str) -> tuple[int, int, int, int]:
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to ``(r, g, b, a)`` ints 0..255."""
    return _channels(hex_str) or _WHITE_RGBA
