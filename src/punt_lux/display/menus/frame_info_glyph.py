"""FrameInfoGlyph — the title-bar "i" disc: where it sits, how it paints, a click.

Painted on the foreground draw list, not as a normal ImGui item: a title bar
sits outside the window's content-area clip rect, which would silently cull an
item placed there (``small_button`` included) before it drew. The foreground
draw list has no such clip rect (as ``DockPill`` relies on too), so the glyph
paints itself by hand and hit-tests the raw mouse position.

Mouse edges on it are read by
:class:`~punt_lux.display.menus.glyph_click.GlyphClick`: a click is the release
of a press that did not drag, and the press edge is reported too.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from imgui_bundle import ImVec2

from punt_lux.display.menus.glyph_click import GlyphClick

if TYPE_CHECKING:
    from punt_lux.display.menus.glyph_click import GlyphReading

__all__ = ["FrameInfoGlyph"]


@final
class FrameInfoGlyph:
    """The info disc, just left of the frame's native close x."""

    # ASCII "i": primary font + fallback lack U+24D8 "ⓘ", which renders as tofu.
    _LABEL = "i"
    _GAP = 4.0
    _SCALE = 0.625  # glyph diameter as a fraction of the title-bar band

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, imgui: Any) -> GlyphReading:
        """Paint the glyph into the current window and read the mouse on it.

        The reading's anchor is the glyph's top-left corner, where the popup sits.
        """
        pos = imgui.get_window_pos()
        size = imgui.get_window_size()
        glyph = (band := imgui.get_frame_height()) * self._SCALE
        high = ImVec2(pos.x + size.x - band - self._GAP, pos.y + (band + glyph) / 2)
        low = ImVec2(high.x - glyph, high.y - glyph)
        hovered = self._paint(imgui, low, high)
        return GlyphClick.read(imgui, (low.x, low.y), hovered=hovered)

    @staticmethod
    def _hovered(imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Whether the mouse sits inside the glyph's rect -- raw geometry, since
        the glyph is not a real ImGui item for ImGui to hover."""
        mouse = imgui.get_mouse_pos()
        return bool(low.x <= mouse.x <= high.x and low.y <= mouse.y <= high.y)

    def _paint(self, imgui: Any, low: ImVec2, high: ImVec2) -> bool:
        """Fill the glyph's rect and center its label; return whether hovered.

        Reports its own hover state like an ImGui widget returns its result, so
        the caller reads it once for the click test.
        """
        hovered = self._hovered(imgui, low, high)
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()
        fill = imgui.Col_.button_hovered if hovered else imgui.Col_.button
        rounding = (high.x - low.x) * 0.5
        draw.add_rect_filled(
            low, high, imgui.get_color_u32(style.color_(fill)), rounding
        )
        text_size = imgui.calc_text_size(self._LABEL)
        text_pos = ImVec2(
            low.x + (high.x - low.x - text_size.x) * 0.5,
            low.y + (high.y - low.y - text_size.y) * 0.5,
        )
        draw.add_text(
            text_pos, imgui.get_color_u32(style.color_(imgui.Col_.text)), self._LABEL
        )
        return hovered
