"""GlyphHit — whether the mouse is on a title-bar glyph that nothing covers.

The glyph is not an ImGui item, so ImGui cannot hover it: the hit test is raw
geometry, and ImGui's window hover is what adds z-order to it.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from imgui_bundle import ImVec2

__all__ = ["GlyphHit"]


@final
class GlyphHit:
    """The mouse is inside a glyph's rect, with nothing but its window in front."""

    # ImGui's name prefix for every popup window.
    _POPUP_PREFIX = "##Popup"

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def is_on(self, imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Whether the mouse is inside the rect ``low``..``high`` and uncovered."""
        mouse = imgui.get_mouse_pos()
        return bool(
            low.x <= mouse.x <= high.x
            and low.y <= mouse.y <= high.y
            and self._is_in_front(imgui)
        )

    def _is_in_front(self, imgui: Any) -> bool:
        """Whether the current window is the one under the mouse, or only a popup is.

        The info popup opens at the glyph, so a second click lands on the popup;
        that click must still reach the glyph, to close or move the popup. A
        popup stacked over the window, or a live title-bar press, must not hide
        the window either, or the press that closes the popup and the release
        that ends a window move would read as not on the glyph.
        """
        flags = (
            imgui.HoveredFlags_.allow_when_blocked_by_popup.value
            | imgui.HoveredFlags_.allow_when_blocked_by_active_item.value
        )
        under = imgui.get_current_context().hovered_window
        # pybind yields None when no window is hovered, though the stub says Window.
        is_popup = bool(under) and under.name.startswith(self._POPUP_PREFIX)
        return bool(imgui.is_window_hovered(flags)) or is_popup
