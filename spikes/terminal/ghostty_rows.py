"""Ghostty render state -> per-row cached draw runs (no ImGui dependency).

Each frame: update the render state, rebuild only dirty rows into runs of
same-styled text plus background spans, then clean the dirty flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyghostty import Terminal, ffi, lib
from pyghostty.core import init_sized

RGB = tuple[int, int, int]


@dataclass(slots=True)
class Run:
    x: int  # first column
    text: str
    ncells: int
    fg: RGB
    bold: bool
    italic: bool
    underline: bool
    wide: bool


@dataclass(slots=True)
class BgSpan:
    x: int
    ncells: int
    color: RGB


@dataclass(slots=True)
class Row:
    runs: list[Run]
    bgs: list[BgSpan]


def _rgb(c: Any) -> RGB:
    return (c.r, c.g, c.b)


class GhosttyRows:
    """Owns a render state for one terminal and a per-row cache of draw runs."""

    def __init__(self, term: Terminal) -> None:
        self.term = term
        self._rs = ffi.new("GhosttyRenderState*")
        lib.ghostty_render_state_new(ffi.NULL, self._rs)
        self._it = ffi.new("GhosttyRenderStateRowIterator*")
        lib.ghostty_render_state_row_iterator_new(ffi.NULL, self._it)
        self._cells = ffi.new("GhosttyRenderStateRowCells*")
        lib.ghostty_render_state_row_cells_new(ffi.NULL, self._cells)
        self._colors = init_sized("GhosttyRenderStateColors")
        self.cursor = init_sized("GhosttyRenderStateCursor")
        # scratch buffers reused for every cell
        self._buf = ffi.new("uint8_t[]", 256)
        self._gb = ffi.new("GhosttyBuffer*")
        self._gb.ptr, self._gb.cap = self._buf, len(self._buf)
        self._c = ffi.new("GhosttyColorRgb*")
        self._st = init_sized("GhosttyStyle")
        self._flag = ffi.new("bool*")
        self._raw = ffi.new("GhosttyCell*")
        self._wide = ffi.new("uint32_t*")
        self._dirty = ffi.new("GhosttyRenderStateDirty*")
        self._row_dirty = ffi.new("bool*")
        self.rows: list[Row] = []
        self.selection: dict[int, tuple[int, int]] = {}  # viewport row -> (x0, x1) inclusive
        self._rsel = init_sized("GhosttyRenderStateRowSelection")
        self.fg: RGB = (220, 220, 220)
        self.bg: RGB = (0, 0, 0)
        self.rebuilt_last_update = 0

    def close(self) -> None:
        lib.ghostty_render_state_row_cells_free(self._cells[0])
        lib.ghostty_render_state_row_iterator_free(self._it[0])
        lib.ghostty_render_state_free(self._rs[0])

    def update(self) -> int:
        """Sync from the terminal; rebuild dirty rows. Returns rows rebuilt."""
        rs = self._rs[0]
        lib.ghostty_render_state_update(rs, self.term._t[0])
        lib.ghostty_render_state_get(rs, lib.GHOSTTY_RENDER_STATE_DATA_COLORS, self._colors)
        lib.ghostty_render_state_get(rs, lib.GHOSTTY_RENDER_STATE_DATA_CURSOR, self.cursor)
        lib.ghostty_render_state_get(rs, lib.GHOSTTY_RENDER_STATE_DATA_DIRTY, self._dirty)
        full = self._dirty[0] == lib.GHOSTTY_RENDER_STATE_DIRTY_FULL
        self.fg, self.bg = _rgb(self._colors.foreground), _rgb(self._colors.background)
        lib.ghostty_render_state_get(rs, lib.GHOSTTY_RENDER_STATE_DATA_ROW_ITERATOR, self._it)
        it = self._it[0]
        rebuilt = y = 0
        self.selection.clear()
        k_sel = lib.GHOSTTY_RENDER_STATE_ROW_DATA_SELECTION
        while lib.ghostty_render_state_row_iterator_next(it):
            if lib.ghostty_render_state_row_get(it, k_sel, self._rsel) == 0:
                self.selection[y] = (self._rsel.start_x, self._rsel.end_x)
            lib.ghostty_render_state_row_get(
                it, lib.GHOSTTY_RENDER_STATE_ROW_DATA_DIRTY, self._row_dirty
            )
            if y >= len(self.rows):
                self.rows.append(self._build_row(it))
                rebuilt += 1
            elif full or self._row_dirty[0]:
                self.rows[y] = self._build_row(it)
                rebuilt += 1
            y += 1
        del self.rows[y:]
        lib.ghostty_render_state_clean(rs)
        self.rebuilt_last_update = rebuilt
        return rebuilt

    def _build_row(self, it: Any) -> Row:
        lib.ghostty_render_state_row_get(it, lib.GHOSTTY_RENDER_STATE_ROW_DATA_CELLS, self._cells)
        cells = self._cells[0]
        get = lib.ghostty_render_state_row_cells_get
        nxt = lib.ghostty_render_state_row_cells_next
        k_utf8 = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_UTF8
        k_bg = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_BG_COLOR
        k_fg = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_FG_COLOR
        k_hs = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_HAS_STYLING
        k_st = lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_STYLE
        buf, gb, c, st, flag = self._buf, self._gb, self._c, self._st, self._flag
        default_fg, default_bg = self.fg, self.bg
        runs: list[Run] = []
        bgs: list[BgSpan] = []
        run: Run | None = None
        x = 0
        while nxt(cells):
            n = gb.len if get(cells, k_utf8, gb) == 0 else 0
            text = ffi.buffer(buf, n)[:].decode("utf-8", "replace") if n else ""
            bg: RGB | None = _rgb(c) if get(cells, k_bg, c) == 0 else None
            fg = default_fg
            bold = italic = underline = False
            get(cells, k_hs, flag)
            if flag[0]:
                get(cells, k_st, st)
                if get(cells, k_fg, c) == 0:
                    fg = _rgb(c)
                bold, italic, underline = bool(st.bold), bool(st.italic), st.underline > 0
                if st.inverse:
                    fg, bg = (bg or default_bg), fg
                if st.invisible:
                    text = ""
            if bg is not None and bg != default_bg:
                last = bgs[-1] if bgs else None
                if last and last.color == bg and last.x + last.ncells == x:
                    last.ncells += 1
                else:
                    bgs.append(BgSpan(x, 1, bg))
            if not text:
                run = None
            elif text == " ":
                # a plain space joins the run it follows (its fg is invisible)
                if run is not None and not run.wide and run.x + run.ncells == x:
                    run.text += " "
                    run.ncells += 1
                else:
                    run = None
            else:
                cluster = len(text) > 1  # multi-codepoint grapheme: always its own run
                wide = (cluster or ord(text) >= 0x1100) and self._is_wide(cells)
                if (
                    run is not None
                    and not (wide or cluster or run.wide)
                    and len(run.text) == run.ncells
                    and run.x + run.ncells == x
                    and run.fg == fg
                    and run.bold == bold
                    and run.italic == italic
                    and run.underline == underline
                ):
                    run.text += text
                    run.ncells += 1
                else:
                    run = Run(x, text, 2 if wide else 1, fg, bold, italic, underline, wide)
                    runs.append(run)
                    if cluster:
                        run = None
            x += 1
        for r in runs:  # drop trailing spaces picked up while joining
            stripped = r.text.rstrip(" ")
            r.ncells -= len(r.text) - len(stripped)
            r.text = stripped
        return Row(runs, bgs)

    def _is_wide(self, cells: Any) -> bool:
        lib.ghostty_render_state_row_cells_get(
            cells, lib.GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_RAW, self._raw
        )
        lib.ghostty_cell_get(self._raw[0], lib.GHOSTTY_CELL_DATA_WIDE, self._wide)
        return bool(self._wide[0] == lib.GHOSTTY_CELL_WIDE_WIDE)
