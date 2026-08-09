"""The scalar carrier-typed value accessors for ContinuousEditArbiter.

Each ``@final`` leaf is the whole per-type difference between a text and a float
widget: the buffer ``read`` (with its miss policy) and committed ``coerce`` the
arbiter delegates. Each satisfies ``ValueAccessor`` structurally, no base class.
The color_picker's accessor is ``RgbaBuffer`` — its buffer has a shape, which
takes a module.
"""

from __future__ import annotations

from typing import SupportsFloat, cast, final

from punt_lux.display.replica.widget_state import WidgetState

__all__ = ["FloatValueAccessor", "StrValueAccessor"]


@final
class StrValueAccessor:
    """Value accessor for input_text — the empty-string miss policy lives here."""

    __slots__ = ()

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

    __slots__ = ()

    def read(self, state: WidgetState, key: str, hub_value: float) -> float:
        """Return the buffer float; a miss falls back to the current Hub value."""
        return state.get_float(key, default=hub_value)

    def coerce(self, stored: object) -> float:
        """Coerce a stored committed value to ``float``; the slot holds a float."""
        return float(cast("SupportsFloat", stored))
