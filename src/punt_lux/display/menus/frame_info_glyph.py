"""FrameInfoGlyph — the title-bar "i" disc: where it sits, how it paints, a click.

Placed just left of the frame's native close x, painted by
:class:`~punt_lux.display.menus.glyph_painter.GlyphPainter`, and hit-tested by
:class:`~punt_lux.display.menus.glyph_hit.GlyphHit`, which counts the mouse only
while nothing but this frame (or the info popup) is in front of the disc.

Mouse edges on it are read by
:class:`~punt_lux.display.menus.glyph_reading.GlyphReading`: a click is the
release of a press that did not drag, and the press edge is reported too.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import Any, Self, final

from imgui_bundle import ImVec2

from punt_lux.display.menus.glyph_hit import GlyphHit
from punt_lux.display.menus.glyph_painter import GlyphPainter
from punt_lux.display.menus.glyph_reading import GlyphReading

__all__ = ["FrameInfoGlyph"]


@final
class FrameInfoGlyph:
    """The info disc, just left of the frame's native close x."""

    _GAP = 4.0
    _SCALE = 0.625  # glyph diameter as a fraction of the title-bar band

    _hit: GlyphHit
    _painter: GlyphPainter
    __slots__ = ("_hit", "_painter")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._hit = GlyphHit()
        self._painter = GlyphPainter()
        return self

    def render(self, imgui: Any) -> GlyphReading:
        """Paint the glyph into the current window and read the mouse on it.

        The reading's anchor is the glyph's top-left corner, where the popup sits.
        """
        pos, size = imgui.get_window_pos(), imgui.get_window_size()
        far = ImVec2(pos.x + size.x, pos.y + size.y)
        glyph = (band := imgui.get_frame_height()) * self._SCALE
        high = ImVec2(far.x - band - self._GAP, pos.y + (band + glyph) / 2)
        low = ImVec2(high.x - glyph, high.y - glyph)
        hovered = self._hit.is_on(imgui, low, high)
        self._painter.paint(imgui, (pos, far), (low, high), hovered=hovered)
        return GlyphReading.read(imgui, (low.x, low.y), hovered=hovered)
