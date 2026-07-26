"""FrameTiling — grid placement for the fit-all frame layout.

Computes equal-cell positions for the frames that fill the content region when
the user requests fit-all. Extracted from the render loop so the placement math
is a small, named unit apart from the ImGui frame loop that consumes it.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from punt_lux.scene import Frame

__all__ = ["FrameTiling"]

# frame_id -> (x, y, width, height) placement for one grid cell.
type Cells = dict[str, tuple[float, float, float, float]]

# Cell floors keep a very small window from producing zero/negative cells; a
# frame may then extend past the viewport, where ImGui scroll handles it.
_MIN_CELL_W = 200.0
_MIN_CELL_H = 150.0
_GAP = 4.0


class FrameTiling:
    """Place frames in a roughly-equal grid filling the content region."""

    _frames: list[Frame]
    __slots__ = ("_frames",)

    def __new__(cls, frames: list[Frame]) -> Self:
        self = super().__new__(cls)
        self._frames = frames
        return self

    def cells(self, imgui: Any, region: Any) -> Cells:
        """Return ``frame_id -> (x, y, w, h)`` for each frame in the grid."""
        n = len(self._frames)
        if n == 0:
            return {}
        origin = imgui.get_cursor_screen_pos()
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        cell_w = max((region.x - _GAP * (cols + 1)) / cols, _MIN_CELL_W)
        cell_h = max((region.y - _GAP * (rows + 1)) / rows, _MIN_CELL_H)
        result: Cells = {}
        for i, frame in enumerate(self._frames):
            col = i % cols
            row = i // cols
            x = origin.x + _GAP + col * (cell_w + _GAP)
            y = origin.y + _GAP + row * (cell_h + _GAP)
            result[frame.frame_id] = (x, y, cell_w, cell_h)
        return result
