"""RgbaBuffer — the color picker's value accessor for ContinuousEditArbiter.

The sibling accessors for text and float are a line each and live together in
``continuous_edit_accessors``; this one is a module because its buffer has a
*shape*. A color picker's in-progress edit lives in ``WidgetState`` like any
other continuous edit, but reading it back means answering what three or four
channels, a malformed slot, or an absent one resolve to — and that is not
something the generic key-value store has any business knowing.

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
    from punt_lux.display.replica.widget_state import WidgetState
    from punt_lux.protocol.elements.rgba_color import Rgba

__all__ = ["RgbaBuffer"]


@final
class RgbaBuffer:
    """Value accessor for color_picker — arity-4 RGBA; a miss reads hub_value."""

    __slots__ = ()

    def read(self, state: WidgetState, key: str, hub_value: Rgba) -> Rgba:
        """Return the buffer tuple; a miss falls back to the current Hub color.

        A stored value that is not three or four finite non-bool numbers is a
        miss too. The return is always arity 4 — a length-3 tuple pads its alpha
        to opaque — because tuple equality needs a fixed arity.
        """
        stored = self._as_rgba4(state.get(key))
        return stored if stored is not None else hub_value

    def coerce(self, stored: object) -> Rgba:
        """Coerce a stored committed value to an arity-4 RGBA tuple."""
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
