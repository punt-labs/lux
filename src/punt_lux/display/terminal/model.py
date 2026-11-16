"""Plain data the row builder produces and the painter consumes.

A ``Row`` is one terminal line, already reduced to what drawing needs:
text ``Run``\\ s (consecutive cells sharing a style, drawn with one
``add_text`` call) and background ``BgSpan``\\ s (consecutive cells sharing a
non-default background, drawn with one rectangle). Rows are rebuilt only when
Ghostty marks them dirty, so this is also the render cache.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RGB", "BgSpan", "CellStyle", "Row", "Run"]

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class CellStyle:
    """The visual attributes a run shares, with colours already resolved."""

    fg: RGB
    bg: RGB | None  # None: the terminal's default background
    bold: bool = False
    italic: bool = False
    underline: bool = False
    invisible: bool = False


@dataclass(slots=True)
class Run:
    """Consecutive cells drawn with one ``add_text`` call.

    ``ncells`` can differ from ``len(text)``: a wide (CJK/emoji) glyph is one
    character in two cells, and a grapheme cluster is several code points in
    one or two cells. Such runs are always a single glyph.
    """

    x: int  # first column
    text: str
    ncells: int
    fg: RGB
    bold: bool = False
    italic: bool = False
    underline: bool = False
    wide: bool = False


@dataclass(slots=True)
class BgSpan:
    """Consecutive cells sharing one non-default background colour."""

    x: int
    ncells: int
    color: RGB


@dataclass(slots=True)
class Row:
    """One terminal line, reduced to text runs and background spans."""

    runs: list[Run]
    bgs: list[BgSpan]
