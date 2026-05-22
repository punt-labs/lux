"""Shared color parsing helpers for per-kind renderers.

PY-OO-7 exception #3: stateless primitives used across multiple renderer
modules.  Lifted from element_renderer.py so the per-kind classes need
not pull the whole ElementRenderer surface for two parser utilities.
"""

from __future__ import annotations

__all__ = ["parse_hex_color", "parse_rgba"]


_WHITE_RGBA: tuple[int, int, int, int] = (255, 255, 255, 255)


def parse_hex_color(hex_str: str) -> tuple[float, float, float, float]:
    """Parse ``"#RRGGBB"`` or ``"#RRGGBBAA"`` to ``(r, g, b, a)`` floats 0..1.

    Returns opaque white on malformed input (renderer fallback behaviour).
    """
    s = hex_str.lstrip("#")
    try:
        if len(s) == 6:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            return (r / 255.0, g / 255.0, b / 255.0, 1.0)
        if len(s) == 8:
            r = int(s[0:2], 16)
            g, b, a = int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
            return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    except ValueError:
        pass
    return (1.0, 1.0, 1.0, 1.0)


def parse_rgba(hex_str: str) -> tuple[int, int, int, int]:
    """Parse ``"#RRGGBB"`` or ``"#RRGGBBAA"`` to ``(r, g, b, a)`` ints 0..255."""
    s = hex_str.lstrip("#")
    try:
        if len(s) == 6:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            return (r, g, b, 255)
        if len(s) == 8:
            r = int(s[0:2], 16)
            g, b, a = int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
            return (r, g, b, a)
    except ValueError:
        pass
    return _WHITE_RGBA
