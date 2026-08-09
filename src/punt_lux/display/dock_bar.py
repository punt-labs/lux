# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportMissingModuleSource=false
"""The strip along the bottom edge holding one pill per minimized frame.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs. It is handed in
rather than imported so the bar paints into the caller's frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

from punt_lux.display.dock_pill import DockPill

if TYPE_CHECKING:
    from punt_lux.display.replica import Frame, SceneReplica

__all__ = ["DOCK_BAR_HEIGHT", "DockBar"]

# Height of the strip. The World panel hit-tests before the bar is painted, so it
# rejects this region by hand and needs the same number.
DOCK_BAR_HEIGHT = 28.0

_PILL_PAD = 6.0
_PILL_GAP = 4.0


@final
class DockBar:
    """Lay minimized frames out as pills, and restore the one that was clicked.

    The bar is drawn on ImGui's foreground draw list so it stays visible whatever
    the window stacking is. What each pill looks like and where its edges are is
    :class:`~punt_lux.display.dock_pill.DockPill`'s; what the strip holds and in
    what order is here.
    """

    _imgui: Any  # the caller's imgui module; imgui_bundle ships no type stubs
    _scenes: SceneReplica
    __slots__ = ("_imgui", "_scenes")

    def __new__(cls, imgui: Any, scenes: SceneReplica) -> Self:
        self = super().__new__(cls)
        self._imgui = imgui
        self._scenes = scenes
        return self

    def render(self, *, any_frame_hovered: bool) -> None:
        """Paint the bar and restore any frame whose pill was clicked.

        *any_frame_hovered* is True when the mouse is over a visible frame
        window, which suppresses pill clicks: a frame overlapping the bar would
        otherwise restore a different frame out from under the click.
        """
        minimized = [f for f in self._scenes.frames.values() if f.minimized]
        if not minimized:
            return
        viewport = self._imgui.get_main_viewport()
        top = viewport.pos.y + viewport.size.y - DOCK_BAR_HEIGHT
        self._paint_chrome(left=viewport.pos.x, top=top, width=viewport.size.x)
        self._paint_pills(
            minimized,
            ImVec2(viewport.pos.x + _PILL_PAD, top + _PILL_PAD),
            viewport.pos.x + viewport.size.x - _PILL_PAD,
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
        self, minimized: list[Frame], anchor: ImVec2, max_x: float, *, clickable: bool
    ) -> None:
        """Lay pills out left to right, ellipsizing once they run out of room."""
        imgui = self._imgui
        draw = imgui.get_foreground_draw_list()
        height = DOCK_BAR_HEIGHT - _PILL_PAD * 2.0
        pill_x = anchor.x

        for frame in minimized:
            pill = DockPill.at(imgui, frame, ImVec2(pill_x, anchor.y), height)
            if pill.right > max_x:
                self._paint_ellipsis(draw, ImVec2(pill_x, anchor.y), height)
                return
            hovered = pill.hovered()
            pill.paint(draw, hovered=hovered)
            if hovered and clickable:
                pill.restore(self._scenes)
            pill_x = pill.right + _PILL_GAP

    def _paint_ellipsis(self, draw: Any, anchor: ImVec2, height: float) -> None:
        """Say that pills were left out, where the next one would have gone."""
        imgui = self._imgui
        text = imgui.calc_text_size("...")
        draw.add_text(
            ImVec2(anchor.x, anchor.y + (height - text.y) * 0.5),
            imgui.get_color_u32(imgui.get_style().color_(imgui.Col_.text)),
            "...",
        )
