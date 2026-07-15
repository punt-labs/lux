"""The three carrier-typed value accessors for ContinuousEditArbiter.

Each ``@final`` leaf carries exactly the per-type behavior the shared arbiter
delegates: a buffer ``read`` (with its miss policy) and a committed ``coerce``.
Everything else in the arbiter is carrier-agnostic, so these three tiny classes
are the whole difference between a text, float, and RGBA-tuple widget.

They satisfy ``ValueAccessor`` structurally — no base class — so the arbiter
composes one rather than subclassing per carrier.
"""

from __future__ import annotations

from typing import SupportsFloat, cast, final

from punt_lux.protocol.elements.rgba_color import Rgba, RgbaColor
from punt_lux.scene.widget_state import WidgetState

__all__ = ["ColorValueAccessor", "FloatValueAccessor", "StrValueAccessor"]


@final
class StrValueAccessor:
    """Value accessor for input_text — the empty-string miss policy lives here."""

    def read(self, state: WidgetState, key: str, hub_value: str) -> str:
        """Return the buffer text; a miss reads ``""`` — a cleared field is real state.

        ``hub_value`` is ignored: a cleared field must not fall back to the Hub.
        """
        _ = hub_value
        return state.get_str(key)

    def coerce(self, stored: object) -> str:
        """Coerce a stored committed value to ``str``."""
        return str(stored)


@final
class FloatValueAccessor:
    """Value accessor for slider — every float is a value; a miss reads hub_value."""

    def read(self, state: WidgetState, key: str, hub_value: float) -> float:
        """Return the buffer float; a miss falls back to the current Hub value."""
        return state.get_float(key, default=hub_value)

    def coerce(self, stored: object) -> float:
        """Coerce a stored committed value to ``float``; the slot holds a float."""
        return float(cast("SupportsFloat", stored))


@final
class ColorValueAccessor:
    """Value accessor for color_picker — arity-4 RGBA tuple; a miss reads hub_value."""

    def read(self, state: WidgetState, key: str, hub_value: Rgba) -> Rgba:
        """Return the buffer tuple; a miss falls back to the current Hub color."""
        return state.get_tuple(key, default=hub_value)

    def coerce(self, stored: object) -> Rgba:
        """Coerce a stored committed value to an arity-4 RGBA tuple."""
        return RgbaColor.coerce(stored)
