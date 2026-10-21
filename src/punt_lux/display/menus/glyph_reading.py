"""GlyphReading — what the mouse did to the title-bar glyph this frame.

The glyph overlaps the title bar, so a press on it also starts ImGui's window
move, which re-focuses the frame every frame it is held -- and focusing the
frame closes every popup stacked over it. A popup opened on the press would be
shut a frame later; opened on the release, after the move has ended, it stays.
A press that dragged is a window move, not a click.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

__all__ = ["GlyphReading"]


@dataclass(frozen=True, slots=True)
class GlyphReading:
    """The left-button edges this frame, and where the glyph's popup anchors.

    ``pressed`` is a press over the glyph. ``released`` is the button coming up
    anywhere. ``clicked`` is the release, over the glyph, of a press that never
    dragged -- whether that press began on this glyph is for the caller to settle.
    """

    anchor: tuple[float, float]
    pressed: bool
    released: bool
    clicked: bool

    @classmethod
    def read(cls, imgui: Any, anchor: tuple[float, float], *, hovered: bool) -> Self:
        """Read the edges; ``hovered`` is whether the mouse is over the glyph."""
        released = cls.is_release(imgui)
        return cls(
            anchor,
            pressed=hovered & cls._is_press(imgui),
            released=released,
            clicked=hovered & released & cls._is_undragged(imgui),
        )

    @staticmethod
    def is_release(imgui: Any) -> bool:
        """Whether the left button came up this frame, over the glyph or not."""
        return bool(imgui.is_mouse_released(imgui.MouseButton_.left))

    @staticmethod
    def _is_press(imgui: Any) -> bool:
        """Whether the left button went down this frame."""
        return bool(imgui.is_mouse_clicked(imgui.MouseButton_.left))

    @staticmethod
    def _is_undragged(imgui: Any) -> bool:
        """Whether the press now ending never strayed past the drag threshold.

        Reads the farthest the press ever strayed, not where it ended: a drag
        that returns to its starting point is still a window move.
        """
        left = imgui.MouseButton_.left
        io = imgui.get_io()
        return bool(
            io.mouse_drag_max_distance_sqr[left.value] < io.mouse_drag_threshold**2
        )
