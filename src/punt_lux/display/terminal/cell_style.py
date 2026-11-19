"""Resolved terminal cell attributes shared by the decoder and painter."""

from __future__ import annotations

from dataclasses import dataclass

type RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class CellStyle:
    """The visual attributes a run shares, with colours already resolved."""

    fg: RGB
    bg: RGB | None  # None: the terminal's default background
    bold: bool = False
    italic: bool = False
    underline: bool = False
    invisible: bool = False
