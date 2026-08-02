"""The color picker's buffer policy — reading a stored RGBA edit back out.

A color picker's in-progress edit lives in ``WidgetState`` like any other
continuous edit, but unlike a text or float buffer its stored value has a shape:
three or four finite channels. Reading it back means answering what a malformed
or absent slot resolves to, and that question belongs here rather than on the
generic store, which has no business knowing what an RGBA tuple looks like.

The read is deliberately lenient where ``RgbaColor.coerce`` is strict. ``coerce``
is the commit path, where a bad value is a bug worth raising on; ``read`` is the
per-frame buffer path, where an unreadable slot simply means the display owes the
user the current Hub color. Neither clamps: ``resolve``'s editing branch returns
this buffer uncoerced, and the reconciliation closes its echo window on tuple
equality, so a value must survive the round trip byte for byte.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast, final

from punt_lux.protocol.elements.rgba_color import RgbaColor

if TYPE_CHECKING:
    from punt_lux.protocol.elements.rgba_color import Rgba
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["RgbaBuffer"]


@final
class RgbaBuffer:
    """Read and coerce a color picker's stored RGBA edit."""

    __slots__ = ()

    @classmethod
    def read(cls, state: WidgetState, key: str, default: Rgba) -> Rgba:
        """Return the stored buffer as arity-4 RGBA, or ``default``.

        A miss falls back to the caller's default (the current Hub color), and so
        does a stored value that is not three or four finite non-bool numbers.
        The return is always arity 4 — a length-3 tuple pads its alpha to opaque
        — because tuple equality needs a fixed arity.
        """
        stored = cls._as_rgba4(state.get(key))
        return stored if stored is not None else default

    @staticmethod
    def coerce(stored: object) -> Rgba:
        """Return a committed value as arity-4 RGBA — the ``resolve`` return cast."""
        return RgbaColor.coerce(stored)

    @staticmethod
    def _as_rgba4(value: object) -> Rgba | None:
        # PY-TS-14 OK: ``None`` is the internal "not a valid RGBA tuple" signal
        # ``read`` maps to its default — it never escapes to a caller.
        if not isinstance(value, tuple):
            return None
        comps = cast("tuple[object, ...]", value)
        if len(comps) not in (3, 4):
            return None
        floats: list[float] = []
        for c in comps:
            if isinstance(c, bool) or not isinstance(c, int | float):
                return None
            if not math.isfinite(c):
                return None
            floats.append(float(c))
        if len(floats) == 3:
            floats.append(1.0)
        return (floats[0], floats[1], floats[2], floats[3])
