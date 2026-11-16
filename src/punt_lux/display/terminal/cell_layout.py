"""Bit layout of the packed GhosttyCell, read from the linked library's manifest.

The header says bit positions are not ABI-stable and must be parsed from
ghostty_type_json(), so nothing here is hard-coded except field names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pyghostty import ffi, lib


@dataclass(frozen=True, slots=True)
class Field:
    lsb: int
    width: int

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1


@dataclass(frozen=True, slots=True)
class CellLayout:
    content_tag: Field
    codepoint: Field  # absolute position (content lsb + arm lsb)
    style_id: Field
    wide: Field
    tag_codepoint: int
    tag_grapheme: int
    tag_bg_palette: int
    tag_bg_rgb: int
    wide_wide: int
    wide_spacer_tail: int
    bg_palette_index: Field
    bg_r: Field
    bg_g: Field
    bg_b: Field


def load_layout() -> CellLayout:
    types = json.loads(ffi.string(lib.ghostty_type_json()).decode())["types"]
    bits = types["GhosttyCell"]["bits"]
    content = bits["content"]
    base = content["lsb"]
    arms = content["arms"]

    def f(d: dict[str, int], off: int = 0) -> Field:
        return Field(d["lsb"] + off, d["width"])

    cp = arms["CODEPOINT"]["bits"]["codepoint"]
    pal = arms["BG_COLOR_PALETTE"]["bits"]["index"]
    rgb = arms["BG_COLOR_RGB"]["bits"]
    tags = types["GhosttyCellContentTag"]["values"]
    wides = types["GhosttyCellWide"]["values"]
    return CellLayout(
        content_tag=f(bits["content_tag"]),
        codepoint=f(cp, base),
        style_id=f(bits["style_id"]),
        wide=f(bits["wide"]),
        tag_codepoint=tags["CODEPOINT"],
        tag_grapheme=tags["CODEPOINT_GRAPHEME"],
        tag_bg_palette=tags["BG_COLOR_PALETTE"],
        tag_bg_rgb=tags["BG_COLOR_RGB"],
        wide_wide=wides["WIDE"],
        wide_spacer_tail=wides["SPACER_TAIL"],
        bg_palette_index=f(pal, base),
        bg_r=f(rgb["r"], base),
        bg_g=f(rgb["g"], base),
        bg_b=f(rgb["b"], base),
    )
