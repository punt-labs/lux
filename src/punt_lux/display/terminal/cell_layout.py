# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""Bit layout of the packed ``GhosttyCell``, read from the linked library.

The row builder decodes a whole row of packed 64-bit cells with numpy in one
pass (ADR-0003). libghostty-vt says bit positions are *not* ABI-stable and
must be read from the ``ghostty_type_json()`` manifest of the library actually
loaded, so nothing here hard-codes a bit position, only field names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np

from punt_lux.display.terminal.ffi import ffi, lib

__all__ = ["CellLayout", "Field", "cell_layout"]


@dataclass(frozen=True, slots=True)
class Field:
    """A bit field inside the packed 64-bit cell."""

    lsb: int
    width: int

    def extract(self, cells: np.ndarray) -> np.ndarray:
        """Return this field of every cell in ``cells`` (a ``uint64`` array)."""
        mask = np.uint64((1 << self.width) - 1)
        return (cells >> np.uint64(self.lsb)) & mask


@dataclass(frozen=True, slots=True)
class CellLayout:
    """Fields and enum values the row builder needs; codepoint is absolute."""

    content_tag: Field
    codepoint: Field
    style_id: Field
    wide: Field
    tag_codepoint: int
    tag_grapheme: int
    tag_bg_palette: int
    tag_bg_rgb: int
    wide_wide: int
    wide_spacer_tail: int


@cache
def cell_layout() -> CellLayout:
    """Read the layout once from the loaded library's type manifest."""
    types: dict[str, Any] = json.loads(ffi.string(lib.ghostty_type_json()).decode())[
        "types"
    ]
    bits = types["GhosttyCell"]["bits"]
    content = bits["content"]  # a tagged union; its arms start at content.lsb

    def field(spec: dict[str, int], offset: int = 0) -> Field:
        return Field(spec["lsb"] + offset, spec["width"])

    tags = types["GhosttyCellContentTag"]["values"]
    wides = types["GhosttyCellWide"]["values"]
    return CellLayout(
        content_tag=field(bits["content_tag"]),
        codepoint=field(
            content["arms"]["CODEPOINT"]["bits"]["codepoint"], content["lsb"]
        ),
        style_id=field(bits["style_id"]),
        wide=field(bits["wide"]),
        tag_codepoint=tags["CODEPOINT"],
        tag_grapheme=tags["CODEPOINT_GRAPHEME"],
        tag_bg_palette=tags["BG_COLOR_PALETTE"],
        tag_bg_rgb=tags["BG_COLOR_RGB"],
        wide_wide=wides["WIDE"],
        wide_spacer_tail=wides["SPACER_TAIL"],
    )
