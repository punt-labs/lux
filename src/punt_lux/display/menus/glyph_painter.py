"""GlyphPainter — draws the title-bar "i" disc onto its window's own draw list.

A title bar sits outside the window's content-area clip rect, which would
silently cull an item placed there (``small_button`` included) before it drew,
so the disc paints itself by hand. The window's own list, with a clip rect
widened to the whole window, reaches the title bar yet still obeys z-order: a
frame in front covers the disc, which the global foreground list would not.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

from imgui_bundle import ImVec2

__all__ = ["GlyphPainter"]


@final
class GlyphPainter:
    """Fill the disc's rect and center its label."""

    # ASCII "i": primary font + fallback lack U+24D8 "ⓘ", which renders as tofu.
    _LABEL = "i"

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def paint(
        self,
        imgui: Any,
        window: tuple[ImVec2, ImVec2],
        disc: tuple[ImVec2, ImVec2],
        *,
        hovered: bool,
    ) -> None:
        """Paint the disc ``low..high``, clipped to the ``window`` rect."""
        low, high = disc
        draw = imgui.get_window_draw_list()
        style = imgui.get_style()
        fill = imgui.Col_.button_hovered if hovered else imgui.Col_.button
        # Not intersected with the content clip rect, which excludes the title bar.
        draw.push_clip_rect(*window, intersect_with_current_clip_rect=False)
        draw.add_rect_filled(
            low, high, imgui.get_color_u32(style.color_(fill)), (high.x - low.x) / 2
        )
        text_size = imgui.calc_text_size(self._LABEL)
        text_pos = ImVec2(
            low.x + (high.x - low.x - text_size.x) * 0.5,
            low.y + (high.y - low.y - text_size.y) * 0.5,
        )
        draw.add_text(
            text_pos, imgui.get_color_u32(style.color_(imgui.Col_.text)), self._LABEL
        )
        draw.pop_clip_rect()
