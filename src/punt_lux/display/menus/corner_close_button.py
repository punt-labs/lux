"""CornerCloseButton -- a small button flush with an auto-sized window's right edge.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

__all__ = ["CornerCloseButton"]


@final
class CornerCloseButton:
    """A button drawn on the line that began at *origin*, after the content.

    It aims at the right edge of what has been drawn this frame, not at the
    window's settled width and not at the width left over: either would feed the
    button back into an auto-sized window and make its width breathe. Clamped to
    clear *lead*, the text that began the line, so a line wider than the content
    pushes the button out rather than over it.
    """

    _label: str
    _lead: str
    _origin: Any  # an ImVec2: imgui_bundle ships no stubs
    __slots__ = ("_label", "_lead", "_origin")

    def __new__(cls, label: str, lead: str, origin: Any) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._lead = lead
        self._origin = origin
        return self

    def render(self, imgui: Any) -> bool:
        """Draw the button; return whether it was pressed."""
        style = imgui.get_style()
        width = imgui.calc_text_size(self._label).x + style.frame_padding.x * 2.0
        lead_end = self._origin.x + imgui.calc_text_size(self._lead).x
        right_edge = imgui.internal.get_current_window_read().dc.cursor_max_pos.x
        left = max(right_edge - width, lead_end + style.item_spacing.x)
        # The cursor is left on the button's line: ImGui allows moving it only
        # because the button, an item, follows.
        imgui.set_cursor_screen_pos(imgui.ImVec2(left, self._origin.y))
        return bool(imgui.small_button(self._label))
