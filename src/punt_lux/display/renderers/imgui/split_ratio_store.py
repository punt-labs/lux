"""The Display-local grid/detail split ratio for one split pane, per scene.

The draggable divider between a composed table's grid and detail is Display-local
view state, like a column width. This store owns that ratio — the top pane's
height fraction — in the per-scene ``WidgetState`` keyed by the pane's element id,
so it survives the poller replacing the scene and stays isolated from other panes.

The store imposes no layout policy: the usable-height floor (grid rows, detail
lines) is the renderer's per-frame pixel decision and the single clamp authority
— on a tall pane those floors sit at fractions outside any coarse band, so a band
here would snap a legitimate drag back on release. The store keeps only a
degenerate guard against ``0``/``1``/``NaN``, confining the fraction to ``(0,1)``.
"""

from __future__ import annotations

import math
from typing import Self, final

from punt_lux.scene.widget_state import WidgetState

__all__ = ["SplitRatioStore"]

# Degenerate guard only — reject 0/1/NaN, not layout policy. The renderer's
# per-frame pixel floors are the real (and single) clamp authority.
_MIN_RATIO = 0.01
_MAX_RATIO = 0.99


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

        A non-finite corrupted slot falls back to ``default``; the result is
        confined to ``(0, 1)``. The usable-height floor is the renderer's.
        """
        stored = self._state.get_float(self._key, default)
        return self._clamp(stored if math.isfinite(stored) else default)

    def set_ratio(self, value: float) -> None:
        """Store ``value`` as the top-height fraction; ignore non-finite garbage."""
        if math.isfinite(value):
            self._state.set(self._key, self._clamp(value))

    @staticmethod
    def _clamp(value: float) -> float:
        """Confine a finite fraction to the degenerate guard band ``(0, 1)``."""
        return min(max(value, _MIN_RATIO), _MAX_RATIO)
