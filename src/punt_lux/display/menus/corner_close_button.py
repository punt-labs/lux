"""CornerCloseButton -- ImGui's close cross, flush with a window's right edge.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

__all__ = ["CornerCloseButton"]


@final
class CornerCloseButton:
    """ImGui's native close cross, centred on the title line that began at *origin*.

    Aimed at the right edge of what is drawn so far, never the window's settled
    width, which would feed back into an auto-sized window and make it breathe;
    clamped to clear *lead*, the title text, so a long title pushes it out.
    """

    _ID = "##close"

    _lead: str
    _origin: Any  # an ImVec2: imgui_bundle ships no stubs
    __slots__ = ("_lead", "_origin")

    def __new__(cls, lead: str, origin: Any) -> Self:
        self = super().__new__(cls)
        self._lead = lead
        self._origin = origin
        return self

    def render(self, imgui: Any) -> bool:
        """Draw the button; return whether it was pressed."""
        size = imgui.get_font_size()
        lead_end = self._origin.x + imgui.calc_text_size(self._lead).x
        right_edge = imgui.internal.get_current_window_read().dc.cursor_max_pos.x
        left = max(right_edge - size, lead_end + imgui.get_style().item_spacing.x)
        top = self._origin.y + (imgui.get_text_line_height() - size) / 2.0
        pos = imgui.ImVec2(left, top)
        pressed = bool(imgui.internal.close_button(imgui.get_id(self._ID), pos))
        # close_button reserves no layout space; the window must widen for it.
        imgui.set_cursor_screen_pos(pos)
        imgui.dummy(imgui.ImVec2(size, size))
        return pressed
