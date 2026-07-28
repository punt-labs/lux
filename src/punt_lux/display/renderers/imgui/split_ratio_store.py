"""The Display-local grid/detail split ratio for one split pane, per scene.

The draggable divider between a composed table's grid and detail is view state
that belongs to the Display, exactly like a column width or the Display-side
sort: a drag reallocates the two pane heights with no Hub round-trip. This store
owns that ratio — the top pane's height fraction — in the per-scene
``WidgetState`` keyed by the pane's element id, so it survives the poller
replacing the composed scene every few seconds and stays isolated from any other
pane in the same or another scene. The stored value is clamped to a coarse band
so a corrupt slot can never collapse a pane to nothing; the exact usable-height
floor (grid rows, detail lines) is a pixel decision the renderer makes with the
frame's available height.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["SplitRatioStore"]

# Coarse guard band for the stored fraction — the renderer applies the real
# per-frame pixel floor. Kept away from 0/1 so neither pane can vanish outright.
_MIN_RATIO = 0.1
_MAX_RATIO = 0.9


@final
class SplitRatioStore:
    """Read and write one split pane's top-height fraction in its scene slot."""

    _state: WidgetState
    _key: str
    __slots__ = ("_key", "_state")

    def __new__(cls, state: WidgetState, element_id: str) -> Self:
        self = super().__new__(cls)
        self._state = state
        self._key = f"{element_id}{WidgetState.SPLIT_RATIO_SUFFIX}"
        return self

    def ratio(self, default: float) -> float:
        """Return the stored top-height fraction, or ``default`` when unset.

        Both the stored value and the default are clamped to the guard band, so a
        caller passing an out-of-band default (or a slot corrupted to a bad type)
        still gets a usable fraction rather than a collapsed pane.
        """
        stored = self._state.get_float(self._key, default)
        return self._clamp(stored)

    def set_ratio(self, value: float) -> None:
        """Store ``value`` as the top-height fraction, clamped to the guard band."""
        self._state.set(self._key, self._clamp(value))

    @staticmethod
    def _clamp(value: float) -> float:
        """Return ``value`` confined to the coarse guard band."""
        return min(max(value, _MIN_RATIO), _MAX_RATIO)
