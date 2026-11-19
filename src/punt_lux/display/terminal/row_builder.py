"""One terminal row → text runs and background spans (ADR-0003).

The hot path of the whole renderer. A row of 200 cells could cost 200+ FFI
calls if read cell by cell, which is too slow in Python under load (STEP1.md:
up to 37 ms for a full redraw). Instead:

1. **One call per row** fetches all packed cells
   (``GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW``); numpy decodes the code
   point, style id, wide flag and content tag of every cell at once.
2. **Plain rows** (no styles, no wide cells, no clusters: most shell output)
   become a single run with no further calls.
3. **Mixed rows** are split into segments where the style id changes or a
   special cell starts. Per-cell calls remain only for: the first cell of
   each distinct style (cached for the row, because style ids are
   page-local), grapheme clusters, wide cells and background-only cells.

Correctness is checked against the straightforward per-cell reader in
``spikes/terminal/check_fast.py`` on every recording (identical output).
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Self

import numpy as np

from punt_lux.display.terminal.cell_layout import CellLayout, cell_layout
from punt_lux.display.terminal.model import RGB, BgSpan, CellStyle, Row, Run
from punt_lux.terminal.ffi import ffi, init_sized, lib

if TYPE_CHECKING:
    from pyghostty._ffi import (
        GhosttyBufferPointer,
        GhosttyCellsViewPointer,
        GhosttyColorRgbPointer,
        GhosttyRenderStateRowCellsImpl,
        GhosttyRenderStateRowIteratorImpl,
        GhosttyStylePointer,
        Pointer,
    )

__all__ = ["RowBuilder"]


class RowBuilder:
    r"""Builds ``Row``\\ s from a render-state row iterator. Reuses its buffers."""

    _layout: CellLayout
    _cells: Pointer[Pointer[GhosttyRenderStateRowCellsImpl]]
    _view: GhosttyCellsViewPointer
    _color: GhosttyColorRgbPointer
    _style: GhosttyStylePointer
    _utf8: Pointer[int]
    _utf8_buf: GhosttyBufferPointer
    _styles: dict[int, CellStyle]
    _fg: RGB
    _bg: RGB

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._layout = cell_layout()
        self._cells = ffi.new("GhosttyRenderStateRowCells*")
        lib.ghostty_render_state_row_cells_new(ffi.NULL, self._cells)
        self._view = ffi.new("GhosttyCellsView*")
        self._color = ffi.new("GhosttyColorRgb*")
        self._style = init_sized("GhosttyStyle")
        self._utf8 = ffi.new("uint8_t[]", 256)
        self._utf8_buf = ffi.new("GhosttyBuffer*")
        self._utf8_buf.ptr, self._utf8_buf.cap = self._utf8, len(self._utf8)
        self._styles = {}
        self._fg = (204, 204, 204)  # the terminal's defaults, set per update
        self._bg = (30, 30, 30)
        return self

    def close(self) -> None:
        lib.ghostty_render_state_row_cells_free(self._cells[0])

    def build(self, row_iterator: Pointer[GhosttyRenderStateRowIteratorImpl]) -> Row:
        """Build the iterator's current row."""
        lay = self._layout
        lib.ghostty_render_state_row_get(
            row_iterator, lib.GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW, self._view
        )
        n = self._view.len
        raw = np.frombuffer(ffi.buffer(self._view.ptr, n * 8), dtype=np.uint64)
        tag = lay.content_tag.extract(raw)
        codepoints = lay.codepoint.extract(raw).astype(np.uint32)
        style_ids = lay.style_id.extract(raw)
        wide = lay.wide.extract(raw)
        has_text = (tag == lay.tag_codepoint) | (tag == lay.tag_grapheme)
        codepoints[~has_text | (codepoints == 0)] = ord(" ")

        plain = (
            not style_ids.any()
            and not wide.any()
            and bool((tag == lay.tag_codepoint).all())
        )
        if plain:
            text = codepoints.tobytes().decode("utf-32-le").rstrip(" ")
            return Row([Run(0, text, len(text), self._fg)] if text else [], [])

        lib.ghostty_render_state_row_get(
            row_iterator, lib.GHOSTTY_RENDER_STATE_ROW_DATA_CELLS, self._cells
        )
        return self._build_mixed(tag, codepoints, style_ids, wide)

    # -- mixed rows --------------------------------------------------------
    def _build_mixed(
        self,
        tag: np.ndarray,
        codepoints: np.ndarray,
        style_ids: np.ndarray,
        wide: np.ndarray,
    ) -> Row:
        lay = self._layout
        self._styles.clear()  # style ids are page-local: never reuse across rows
        special = (wide != 0) | (tag != lay.tag_codepoint)
        changes = (style_ids[1:] != style_ids[:-1]) | special[1:] | special[:-1]
        bounds = [0, *(np.flatnonzero(changes) + 1).tolist(), len(tag)]
        runs: list[Run] = []
        bgs: list[BgSpan] = []
        for start, end in itertools.pairwise(bounds):
            kind, width = int(tag[start]), int(wide[start])
            if kind in (lay.tag_bg_palette, lay.tag_bg_rgb):  # colour, no text
                if (bg := self._cell_bg(start)) is not None:
                    self._add_bg(bgs, start, end - start, bg, self._bg)
                continue
            if width == lay.wide_spacer_tail:  # second half of a wide glyph
                continue
            style = self._cell_style(int(style_ids[start]), start)
            is_wide = width == lay.wide_wide
            if style.bg is not None:
                ncells = 2 if is_wide else end - start
                self._add_bg(bgs, start, ncells, style.bg, self._bg)
            self._append_text(
                runs, start, end, int(kind), style, codepoints, is_wide=is_wide
            )
        return Row(runs, bgs)

    def _append_text(
        self,
        runs: list[Run],
        start: int,
        end: int,
        kind: int,
        style: CellStyle,
        codepoints: np.ndarray,
        *,
        is_wide: bool,
    ) -> None:
        """Append one text segment; background-only cells are handled upstream."""
        if style.invisible:
            return
        if kind == self._layout.tag_grapheme or is_wide:
            glyph = self._grapheme(start)
            if glyph.strip(" "):
                runs.append(
                    self._run(start, glyph, 2 if is_wide else 1, style, wide=is_wide)
                )
            return
        text = codepoints[start:end].tobytes().decode("utf-32-le").rstrip(" ")
        if text:
            runs.append(self._run(start, text, len(text), style, wide=False))

    def _cell_style(self, style_id: int, x: int) -> CellStyle:
        """Resolve a style id (cached for this row); 0 is the default style."""
        if style_id == 0:
            return CellStyle(self._fg, None)
        if (cached := self._styles.get(style_id)) is not None:
            return cached
        cells, get, st = (
            self._cells[0],
            lib.ghostty_render_state_row_cells_get,
            self._style,
        )
        lib.ghostty_render_state_row_cells_select(cells, x)
        get(cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_STYLE, st)
        fg = (
            self._resolved(lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_FG_COLOR) or self._fg
        )
        bg = self._resolved(lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR)
        if st.inverse:
            fg, bg = (bg or self._bg), fg
        style = CellStyle(
            fg=fg,
            bg=bg,
            bold=bool(st.bold),
            italic=bool(st.italic),
            underline=st.underline > 0,
            invisible=bool(st.invisible),
        )
        self._styles[style_id] = style
        return style

    def _resolved(self, key: int) -> RGB | None:
        """Resolve the selected cell's color, or return ``None`` for the default."""
        c = self._color
        ok = lib.ghostty_render_state_row_cells_get(self._cells[0], key, c) == 0
        return (c.r, c.g, c.b) if ok else None

    def _cell_bg(self, x: int) -> RGB | None:
        lib.ghostty_render_state_row_cells_select(self._cells[0], x)
        return self._resolved(lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR)

    def _grapheme(self, x: int) -> str:
        cells = self._cells[0]
        lib.ghostty_render_state_row_cells_select(cells, x)
        key = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_UTF8
        if lib.ghostty_render_state_row_cells_get(cells, key, self._utf8_buf) != 0:
            return "\ufffd"  # cluster larger than the buffer: not worth showing
        raw: bytes = ffi.buffer(self._utf8, self._utf8_buf.len)[:]
        return raw.decode("utf-8", "replace")

    @property
    def fg(self) -> RGB:
        return self._fg

    @fg.setter
    def fg(self, value: RGB) -> None:
        self._fg = value

    @property
    def bg(self) -> RGB:
        return self._bg

    @bg.setter
    def bg(self, value: RGB) -> None:
        self._bg = value

    @staticmethod
    def _run(x: int, text: str, ncells: int, style: CellStyle, *, wide: bool) -> Run:
        return Run(
            x, text, ncells, style.fg, style.bold, style.italic, style.underline, wide
        )

    @staticmethod
    def _add_bg(
        bgs: list[BgSpan], x: int, ncells: int, color: RGB, default: RGB
    ) -> None:
        """Append a background span, merging with the previous one when adjacent."""
        if color == default:
            return
        last = bgs[-1] if bgs else None
        if last is not None and last.color == color and last.x + last.ncells == x:
            last.ncells += ncells
        else:
            bgs.append(BgSpan(x, ncells, color))
