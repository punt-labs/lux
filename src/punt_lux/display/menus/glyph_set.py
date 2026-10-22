"""GlyphSet — which glyph a frame gets: the info disc, or none without a title bar.

A frame flagged ``no_title_bar`` has nothing to host the disc, which would paint
over its content and intercept the clicks meant for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.frame_info_glyph import FrameInfoGlyph
from punt_lux.display.menus.glyph_reading import GlyphReading

if TYPE_CHECKING:
    from punt_lux.display.menus.glyph_canvas import GlyphCanvas
    from punt_lux.display.replica.frame import Frame

__all__ = ["AbsentGlyph", "GlyphSet"]


@final
class AbsentGlyph:
    """The glyph of a frame that has none: draws nothing and reads no mouse edge."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, _canvas: GlyphCanvas) -> GlyphReading:
        """Report a reading with no press, release, or click."""
        return GlyphReading((0.0, 0.0), pressed=False, released=False, clicked=False)


@final
class GlyphSet:
    """Hands each frame the glyph its window can host."""

    _drawn: FrameInfoGlyph
    _absent: AbsentGlyph
    __slots__ = ("_absent", "_drawn")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._drawn = FrameInfoGlyph()
        self._absent = AbsentGlyph()
        return self

    def for_frame(self, frame: Frame) -> FrameInfoGlyph | AbsentGlyph:
        """Return the disc for a frame with a title bar, else the absent glyph."""
        flags = frame.hints.flags or {}
        return self._absent if flags.get("no_title_bar", False) else self._drawn
