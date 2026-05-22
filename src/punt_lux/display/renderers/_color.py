"""Hex colour parsers — return ``None`` on bad input with a warning.

Float-returning callers must skip the colour push when this returns
``None`` so ImGui's theme default renders.  An always-opaque-white
fallback regressed text rendering: invalid hex turned every label
white instead of preserving the theme.  PY-TS-14 OK on the ``| None``
return — absence is the documented contract: "could not parse, caller
must use theme default."
"""

from __future__ import annotations

import logging

__all__ = ["parse_hex_color", "parse_rgba"]

_log = logging.getLogger(__name__)

_WHITE_RGBA: tuple[int, int, int, int] = (255, 255, 255, 255)


def _channels(hex_str: str) -> tuple[int, int, int, int] | None:
    """Return (r, g, b, a) 0..255 or None on malformed input; log on failure.

    PY-TS-14 OK: the ``| None`` is the documented absence contract — the
    function's job is "parse hex into 0..255 channels"; ``None`` signals
    "no valid parse" so callers can choose their own fallback (opaque
    white for ints, theme default for floats).
    """
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
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to floats 0..1, or ``None`` if invalid.

    PY-TS-14 OK on ``| None``: absence is the documented contract.
    Callers must guard the push — ``if color is not None: push_style_color(...)``
    — so ImGui's theme default renders on malformed input.  Returning
    opaque white here would silently override every styled colour the
    theme provides.
    """
    rgba = _channels(hex_str)
    if rgba is None:
        return None
    r, g, b, a = rgba
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def parse_rgba(hex_str: str) -> tuple[int, int, int, int]:
    """Parse ``"#RRGGBB"`` / ``"#RRGGBBAA"`` to ``(r, g, b, a)`` ints 0..255."""
    return _channels(hex_str) or _WHITE_RGBA
