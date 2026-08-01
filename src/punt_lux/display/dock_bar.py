# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportMissingModuleSource=false
"""The strip along the bottom edge holding one pill per minimized frame.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs. It is handed in
rather than imported so the bar paints into the caller's frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

if TYPE_CHECKING:
    from punt_lux.scene import Frame, SceneManager

__all__ = ["DOCK_BAR_HEIGHT", "DockBar"]

# Height of the strip. The World panel hit-tests before the bar is painted, so it
# rejects this region by hand and needs the same number.
DOCK_BAR_HEIGHT = 28.0

_PILL_PAD = 6.0
_PILL_GAP = 4.0
_PILL_TEXT_PAD = 8.0
_PILL_ROUNDING = 4.0


@final
class DockBar:
    """Paint minimized frames as clickable pills, and restore the one clicked.

    The bar is drawn on ImGui's foreground draw list so it stays visible whatever
    the window stacking is. That has a consequence the layout below works around:
    a foreground draw list has no window in the z-order, so `invisible_button`
    widgets never receive clicks reliably and the pills are hit-tested against the
    raw mouse position instead.
    """

    _imgui: Any  # the caller's imgui module; imgui_bundle ships no type stubs
    _scene_manager: SceneManager

    def __new__(cls, imgui: Any, scene_manager: SceneManager) -> Self:
        self = super().__new__(cls)
        self._imgui = imgui
        self._scene_manager = scene_manager
        return self

    def render(self, *, any_frame_hovered: bool) -> None:
        """Paint the bar and restore any frame whose pill was clicked.

        *any_frame_hovered* is True when the mouse is over a visible frame
        window, which suppresses pill clicks: a frame overlapping the bar would
        otherwise restore a different frame out from under the click.
        """
        minimized = [f for f in self._scene_manager.frames.values() if f.minimized]
        if not minimized:
            return
        viewport = self._imgui.get_main_viewport()
        top = viewport.pos.y + viewport.size.y - DOCK_BAR_HEIGHT
        self._paint_chrome(left=viewport.pos.x, top=top, width=viewport.size.x)
        self._paint_pills(
            minimized,
            left=viewport.pos.x,
            top=top,
            width=viewport.size.x,
            clickable=self._clickable(any_frame_hovered=any_frame_hovered),
        )

    def _clickable(self, *, any_frame_hovered: bool) -> bool:
        """Report whether this frame's click belongs to the dock bar.

        The obvious `is_window_hovered(any_window)` guard is always true here —
        `dock_space_over_viewport` covers the whole viewport — so the caller's
        explicit hover flag is what decides.
        """
        imgui = self._imgui
        return bool(
            imgui.is_mouse_clicked(imgui.MouseButton_.left)
            and not imgui.is_any_item_hovered()
            and not any_frame_hovered
        )

    def _paint_chrome(self, *, left: float, top: float, width: float) -> None:
        """Fill the bar's background and rule its top edge, in theme colours."""
        imgui = self._imgui
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()
        draw.add_rect_filled(
            ImVec2(left, top),
            ImVec2(left + width, top + DOCK_BAR_HEIGHT),
            imgui.get_color_u32(style.color_(imgui.Col_.title_bg)),
        )
        draw.add_line(
            ImVec2(left, top),
            ImVec2(left + width, top),
            imgui.get_color_u32(style.color_(imgui.Col_.border)),
            1.0,
        )

    def _paint_pills(
        self,
        minimized: list[Frame],
        *,
        left: float,
        top: float,
        width: float,
        clickable: bool,
    ) -> None:
        """Lay pills out left to right, ellipsizing once they run out of room."""
        imgui = self._imgui
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()
        text_col = imgui.get_color_u32(style.color_(imgui.Col_.text))
        normal = imgui.get_color_u32(style.color_(imgui.Col_.button))
        hovered_col = imgui.get_color_u32(style.color_(imgui.Col_.button_hovered))

        height = DOCK_BAR_HEIGHT - _PILL_PAD * 2.0
        pill_y = top + _PILL_PAD
        pill_x = left + _PILL_PAD
        max_x = left + width - _PILL_PAD
        mouse = imgui.get_mouse_pos()

        for frame in minimized:
            text_size = imgui.calc_text_size(frame.title)
            pill_w = text_size.x + _PILL_TEXT_PAD * 2.0
            if pill_x + pill_w > max_x:
                ellipsis = imgui.calc_text_size("...")
                ey = pill_y + (height - ellipsis.y) * 0.5
                draw.add_text(ImVec2(pill_x, ey), text_col, "...")
                return
            p_min = ImVec2(pill_x, pill_y)
            p_max = ImVec2(pill_x + pill_w, pill_y + height)
            hovered = p_min.x <= mouse.x <= p_max.x and p_min.y <= mouse.y <= p_max.y
            draw.add_rect_filled(
                p_min, p_max, hovered_col if hovered else normal, _PILL_ROUNDING
            )
            draw.add_text(
                ImVec2(pill_x + _PILL_TEXT_PAD, pill_y + (height - text_size.y) * 0.5),
                text_col,
                frame.title,
            )
            if hovered and clickable:
                frame.minimized = False
                self._scene_manager.request_focus(frame.frame_id)
            pill_x += pill_w + _PILL_GAP
