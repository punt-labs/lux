"""GlyphHit — whether the mouse is on a title-bar glyph that nothing covers.

The glyph is not an ImGui item, so ImGui cannot hover it: the hit test is raw
geometry, and ImGui's window hover is what adds z-order to it.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from imgui_bundle import ImVec2

    from punt_lux.display.menus.glyph_canvas import GlyphCanvas

__all__ = ["GlyphHit"]


@final
class GlyphHit:
    """The mouse is inside a glyph's rect, with nothing but its window in front."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def is_on(self, canvas: GlyphCanvas, low: ImVec2, high: ImVec2) -> bool:
        """Whether the mouse is inside the rect ``low``..``high`` and uncovered."""
        mouse = canvas.imgui.get_mouse_pos()
        return bool(
            low.x <= mouse.x <= high.x
            and low.y <= mouse.y <= high.y
            and self._is_in_front(canvas)
        )

    def _is_in_front(self, canvas: GlyphCanvas) -> bool:
        """Whether this window is under the mouse, or only its own popup is.

        The info popup opens at the glyph, so a second click lands on the popup;
        that click must still reach the glyph, to close or move the popup. Only
        the popup open for this very frame is looked through: any other popup
        in front, or this popup over another frame's glyph, hides it. A focused
        info popup is also looked through for the hover test, and so is a live
        title-bar press, or the press that closes the popup and the release that
        ends a window move would read as not on the glyph.
        """
        imgui, popup = canvas.imgui, canvas.popup
        if popup.is_under_mouse(imgui):
            return True
        flags = imgui.HoveredFlags_.allow_when_blocked_by_active_item.value
        if popup.is_focused(imgui):
            flags |= imgui.HoveredFlags_.allow_when_blocked_by_popup.value
        return bool(imgui.is_window_hovered(flags))
