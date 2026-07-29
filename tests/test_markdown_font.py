"""The packaged DejaVu markdown font ships, covers the arrows, and wires imgui_md.

lux-efun: imgui_md's own text font lacks U+2192, so markdown arrows paint as tofu.
The fix bundles DejaVu (which carries them) and points imgui_md at it. These are
structural guards — the visual confirmation is the demo gate — proving the files
are in the installed layout, cover the glyphs, and that the markdown options route
through the packaged base path.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from punt_lux.display.markdown_font import MarkdownFont

if TYPE_CHECKING:
    import pytest

# The glyphs imgui_md's own Roboto subset omits, which the packaged DejaVu must
# carry — and which the dev-time subset (scripts/subset-markdown-fonts.sh) must keep.
_REQUIRED = (
    0x2192,  # → rightwards arrow (the reported tofu)
    0x2190,  # ← leftwards arrow
    0x2191,  # ↑ upwards arrow
    0x2193,  # ↓ downwards arrow
    0x2014,  # — em dash
)


def _cmap_codepoints(path: Path) -> set[int]:
    """Return the BMP codepoints a TrueType font's format-4 cmap maps."""
    data = path.read_bytes()
    assert data[:4] in (b"\x00\x01\x00\x00", b"true"), f"{path.name} is not a TTF"
    table_count = struct.unpack(">H", data[4:6])[0]
    cmap_off = None
    for i in range(table_count):
        record = 12 + i * 16
        if data[record : record + 4] == b"cmap":
            cmap_off = struct.unpack(">I", data[record + 8 : record + 12])[0]
    assert cmap_off is not None, f"{path.name} has no cmap table"
    subtable_count = struct.unpack(">H", data[cmap_off + 2 : cmap_off + 4])[0]
    fmt4_off = None
    for i in range(subtable_count):
        rec = cmap_off + 4 + i * 8
        sub = cmap_off + struct.unpack(">I", data[rec + 4 : rec + 8])[0]
        if struct.unpack(">H", data[sub : sub + 2])[0] == 4:
            fmt4_off = sub
    assert fmt4_off is not None, f"{path.name} has no format-4 cmap subtable"
    seg_x2 = struct.unpack(">H", data[fmt4_off + 6 : fmt4_off + 8])[0]
    end_off = fmt4_off + 14
    start_off = end_off + seg_x2 + 2
    points: set[int] = set()
    for seg in range(seg_x2 // 2):
        end = struct.unpack(">H", data[end_off + seg * 2 : end_off + seg * 2 + 2])[0]
        start = struct.unpack(
            ">H", data[start_off + seg * 2 : start_off + seg * 2 + 2]
        )[0]
        for cp in range(start, min(end, 0x2300) + 1):
            if cp != 0xFFFF:
                points.add(cp)
    return points


def test_the_four_weight_files_are_packaged() -> None:
    files = MarkdownFont().weight_files()
    assert len(files) == 4
    for path in files:
        assert path.is_file(), f"missing packaged weight: {path}"


def test_the_license_ships_beside_the_fonts() -> None:
    assert (MarkdownFont().search_dir / "dejavu" / "LICENSE").is_file()


def test_every_weight_covers_the_required_glyphs() -> None:
    # The whole point: DejaVu carries the arrows imgui_md's bundled font omits, and
    # the dev-time subset must not have dropped them.
    for path in MarkdownFont().weight_files():
        points = _cmap_codepoints(path)
        missing = [f"U+{cp:04X}" for cp in _REQUIRED if cp not in points]
        assert not missing, f"{path.name} lacks {missing}"


def test_base_path_names_the_packaged_weights() -> None:
    # font_base_path + imgui_md's suffixes must land on the packaged files.
    font = MarkdownFont()
    stem = font.search_dir / font.base_path
    for suffix in ("Regular", "Bold", "BoldItalic", "RegularItalic"):
        assert stem.with_name(f"DejaVu-{suffix}.ttf").is_file()


def test_apply_to_routes_markdown_options_through_the_packaged_font() -> None:
    from imgui_bundle import imgui_md

    registered: list[str] = []
    font = MarkdownFont()
    options = imgui_md.MarkdownOptions()
    font.apply_to(options, registered.append)
    assert options.font_options.font_base_path == font.base_path
    assert registered == [str(font.search_dir)]


def test_apply_to_degrades_to_the_default_font_when_a_weight_is_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A broken install (missing TTFs) must not override font_base_path onto absent
    # files — that fails the load deep in the immapp runner and kills the display.
    # Degrade to imgui_md's default (tofu arrows) with a warning instead.
    from imgui_bundle import imgui_md

    font = MarkdownFont()
    font._dir = tmp_path  # empty — no weight files
    options = imgui_md.MarkdownOptions()
    default_base = options.font_options.font_base_path
    registered: list[str] = []

    with caplog.at_level(logging.WARNING):
        font.apply_to(options, registered.append)

    assert options.font_options.font_base_path == default_base
    assert registered == []
    assert any("missing" in record.getMessage() for record in caplog.records)
