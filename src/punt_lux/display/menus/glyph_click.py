"""GlyphClick — what the mouse did to the title-bar glyph this frame.

The glyph overlaps the title bar, so a press on it also starts ImGui's window
move, which re-focuses the frame every frame it is held -- and focusing the
frame closes every popup stacked over it. A popup opened on the press would be
shut a frame later; opened on the release, after the move has ended, it stays.
A press that dragged is a window move, not a click.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self, final

__all__ = ["GlyphClick", "GlyphReading"]


@dataclass(frozen=True, slots=True)
class GlyphReading:
    """What happened to the glyph this frame, and where its popup anchors."""

    anchor: tuple[float, float]
    pressed: bool
    clicked: bool


@final
class GlyphClick:
    """Reads the left-button press and click edges for one glyph."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def read(
        cls, imgui: Any, anchor: tuple[float, float], *, hovered: bool
    ) -> GlyphReading:
        """Return the press and click edges, which count only while ``hovered``."""
        return GlyphReading(
            anchor,
            pressed=hovered and cls._is_press(imgui),
            clicked=hovered and cls._is_click(imgui),
        )

    @staticmethod
    def _is_press(imgui: Any) -> bool:
        """Whether the left button went down this frame."""
        return bool(imgui.is_mouse_clicked(imgui.MouseButton_.left))

    @staticmethod
    def _is_click(imgui: Any) -> bool:
        """Whether the left button came up after a press that never dragged.

        Reads the farthest the press ever strayed, not where it ended: a drag
        that returns to its starting point is still a window move.
        """
        left = imgui.MouseButton_.left
        if not imgui.is_mouse_released(left):
            return False
        io = imgui.get_io()
        return bool(
            io.mouse_drag_max_distance_sqr[left.value] < io.mouse_drag_threshold**2
        )
