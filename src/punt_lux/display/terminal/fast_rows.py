"""Bulk row builder: one FFI call per row for the packed cells, decoded with numpy.

Per-cell FFI calls happen only for: the first cell of each distinct style in a
row (style + resolved colors, cached per row), grapheme clusters, and wide cells.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
from pyghostty import ffi, lib

from punt_lux.display.terminal.cell_layout import Field, load_layout
from punt_lux.display.terminal.ghostty_rows import RGB, BgSpan, GhosttyRows, Row, Run

L = load_layout()
Style = tuple[
    RGB, RGB | None, bool, bool, bool, bool
]  # fg, bg, bold, italic, underline, invisible


def _bits(raw: np.ndarray, f: Field) -> np.ndarray:
    return (raw >> np.uint64(f.lsb)) & np.uint64(f.mask)


class FastGhosttyRows(GhosttyRows):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._view = ffi.new("GhosttyCellsView*")
        self._styles: dict[int, Style] = {}

    def _build_row(self, it: Any) -> Row:
        lib.ghostty_render_state_row_get(
            it, lib.GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW, self._view
        )
        n = self._view.len
        raw = np.frombuffer(ffi.buffer(self._view.ptr, n * 8), dtype=np.uint64)
        tag = _bits(raw, L.content_tag)
        cp = _bits(raw, L.codepoint).astype(np.uint32)
        sid = _bits(raw, L.style_id)
        wide = _bits(raw, L.wide)
        text_tag = (tag == L.tag_codepoint) | (tag == L.tag_grapheme)
        cp[~text_tag | (cp == 0)] = 32
        if (
            not sid.any()
            and not wide.any()
            and text_tag.all()
            and not (tag == L.tag_grapheme).any()
        ):
            text = cp.tobytes().decode("utf-32-le").rstrip(" ")  # fast path: plain row
            return Row(
                [Run(0, text, len(text), self.fg, False, False, False, False)]
                if text
                else [],
                [],
            )
        return self._build_mixed(it, n, tag, cp, sid, wide)

    def _style(self, sid: int, x: int) -> Style:
        if sid == 0:
            return (self.fg, None, False, False, False, False)
        if (s := self._styles.get(sid)) is not None:
            return s
        cells = self._cells[0]
        lib.ghostty_render_state_row_cells_select(cells, x)
        get, c, st = lib.ghostty_render_state_row_cells_get, self._c, self._st
        get(cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_STYLE, st)
        fg = (
            (c.r, c.g, c.b)
            if get(cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_FG_COLOR, c) == 0
            else self.fg
        )
        bg = (
            (c.r, c.g, c.b)
            if get(cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR, c) == 0
            else None
        )
        if st.inverse:
            fg, bg = (bg or self.bg), fg
        s = (
            fg,
            bg,
            bool(st.bold),
            bool(st.italic),
            st.underline > 0,
            bool(st.invisible),
        )
        self._styles[sid] = s
        return s

    def _cell_bg(self, x: int, tag: int) -> RGB | None:  # bg-only content cells
        cells = self._cells[0]
        lib.ghostty_render_state_row_cells_select(cells, x)
        c = self._c
        ok = lib.ghostty_render_state_row_cells_get(
            cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR, c
        )
        return (c.r, c.g, c.b) if ok == 0 else None

    def _grapheme(self, x: int) -> str:
        cells = self._cells[0]
        lib.ghostty_render_state_row_cells_select(cells, x)
        k = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_UTF8
        if lib.ghostty_render_state_row_cells_get(cells, k, self._gb) != 0:
            return "\ufffd"
        return ffi.buffer(self._buf, self._gb.len)[:].decode("utf-8", "replace")

    def _build_mixed(
        self, it: Any, n: int, tag: Any, cp: Any, sid: Any, wide: Any
    ) -> Row:
        lib.ghostty_render_state_row_get(
            it, lib.GHOSTTY_RENDER_STATE_ROW_DATA_CELLS, self._cells
        )
        self._styles.clear()  # style ids are page-local: never reuse across rows
        special = (wide != 0) | (tag != L.tag_codepoint)
        brk = np.flatnonzero((sid[1:] != sid[:-1]) | special[1:] | special[:-1]) + 1
        bounds = [0, *brk.tolist(), n]
        runs: list[Run] = []
        bgs: list[BgSpan] = []
        for a, b in itertools.pairwise(bounds):
            t = int(tag[a])
            w = int(wide[a])
            if t in (L.tag_bg_palette, L.tag_bg_rgb):
                if (bg := self._cell_bg(a, t)) is not None:
                    _add_bg(bgs, a, b - a, bg, self.bg)
                continue
            if w == L.wide_spacer_tail:
                continue
            fg, bg, bold, italic, ul, invisible = self._style(int(sid[a]), a)
            if bg is not None:
                _add_bg(bgs, a, (2 if w == L.wide_wide else b - a), bg, self.bg)
            if invisible:
                continue
            is_wide = w == L.wide_wide
            if (
                t == L.tag_grapheme or is_wide
            ):  # special cells are always single-cell segments
                text = self._grapheme(a)
                ncells = 2 if is_wide else 1
                if text.strip(" "):
                    runs.append(Run(a, text, ncells, fg, bold, italic, ul, is_wide))
                continue
            stripped = cp[a:b].tobytes().decode("utf-32-le").rstrip(" ")
            if stripped.strip(" "):
                runs.append(
                    Run(a, stripped, len(stripped), fg, bold, italic, ul, False)
                )
        return Row(runs, bgs)


def _add_bg(bgs: list[BgSpan], x: int, ncells: int, color: RGB, default: RGB) -> None:
    if color == default:
        return
    last = bgs[-1] if bgs else None
    if last and last.color == color and last.x + last.ncells == x:
        last.ncells += ncells
    else:
        bgs.append(BgSpan(x, ncells, color))
