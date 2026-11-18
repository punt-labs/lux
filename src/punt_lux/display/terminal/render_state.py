# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""Ghostty's render state, plus a per-row cache of built ``Row``\\ s.

Each frame ``update()`` syncs the render state from the terminal, rebuilds
only the rows Ghostty marks dirty (all of them when it reports a full
redraw), records each row's selection range, and then clears the dirty flags.
An idle terminal therefore costs a few FFI calls per frame (STEP1.md:
0.03-0.06 ms).
"""

from __future__ import annotations

from typing import Any, Self

from punt_lux.display.terminal.ffi import Terminal, ffi, handle, init_sized, lib
from punt_lux.display.terminal.model import RGB, Row
from punt_lux.display.terminal.row_builder import RowBuilder

__all__ = ["RenderState"]


class RenderState:
    """The rows, colours, cursor and selection to draw for one terminal."""

    _term: Terminal
    _state: Any
    _rows_it: Any
    _colors: Any
    _dirty: Any
    _row_dirty: Any
    _row_selection: Any
    _builder: RowBuilder
    _cursor: Any
    _rows: list[Row]
    _selection: dict[int, tuple[int, int]]
    _rebuilt: int

    def __new__(cls, term: Terminal) -> Self:
        self = super().__new__(cls)
        self._term = term
        self._state = ffi.new("GhosttyRenderState*")
        lib.ghostty_render_state_new(ffi.NULL, self._state)
        self._rows_it = ffi.new("GhosttyRenderStateRowIterator*")
        lib.ghostty_render_state_row_iterator_new(ffi.NULL, self._rows_it)
        self._colors = init_sized("GhosttyRenderStateColors")
        self._dirty = ffi.new("GhosttyRenderStateDirty*")
        self._row_dirty = ffi.new("bool*")
        self._row_selection = init_sized("GhosttyRenderStateRowSelection")
        self._builder = RowBuilder()
        self._cursor = init_sized("GhosttyRenderStateCursor")
        self._rows = []
        self._selection = {}  # row -> (x0, x1) inclusive
        self._rebuilt = 0  # rows rebuilt by the last update, for diagnostics
        return self

    @property
    def fg(self) -> RGB:
        return self._builder.fg

    @property
    def bg(self) -> RGB:
        return self._builder.bg

    def close(self) -> None:
        self._builder.close()
        lib.ghostty_render_state_row_iterator_free(self._rows_it[0])
        lib.ghostty_render_state_free(self._state[0])

    def update(self) -> int:
        """Sync from the terminal and rebuild dirty rows; return how many."""
        state = self._state[0]
        lib.ghostty_render_state_update(state, handle(self._term))
        get = lib.ghostty_render_state_get
        get(state, lib.GHOSTTY_RENDER_STATE_DATA_COLORS, self._colors)
        get(state, lib.GHOSTTY_RENDER_STATE_DATA_CURSOR, self._cursor)
        get(state, lib.GHOSTTY_RENDER_STATE_DATA_DIRTY, self._dirty)
        get(state, lib.GHOSTTY_RENDER_STATE_DATA_ROW_ITERATOR, self._rows_it)
        fg, bg = self._colors.foreground, self._colors.background
        self._builder.fg, self._builder.bg = (fg.r, fg.g, fg.b), (bg.r, bg.g, bg.b)

        full = self._dirty[0] == lib.GHOSTTY_RENDER_STATE_DIRTY_FULL
        rows_it = self._rows_it[0]
        self._selection.clear()
        rebuilt = y = 0
        while lib.ghostty_render_state_row_iterator_next(rows_it):
            self._record_selection(rows_it, y)
            if y >= len(self._rows):
                self._rows.append(self._builder.build(rows_it))
                rebuilt += 1
            elif full or self._is_dirty(rows_it):
                self._rows[y] = self._builder.build(rows_it)
                rebuilt += 1
            y += 1
        del self._rows[y:]  # the terminal got shorter
        lib.ghostty_render_state_clean(state)
        self._rebuilt = rebuilt
        return rebuilt

    def _is_dirty(self, rows_it: Any) -> bool:
        key = lib.GHOSTTY_RENDER_STATE_ROW_DATA_DIRTY
        lib.ghostty_render_state_row_get(rows_it, key, self._row_dirty)
        return bool(self._row_dirty[0])

    def _record_selection(self, rows_it: Any, y: int) -> None:
        key = lib.GHOSTTY_RENDER_STATE_ROW_DATA_SELECTION
        if lib.ghostty_render_state_row_get(rows_it, key, self._row_selection) == 0:
            self._selection[y] = (
                self._row_selection.start_x,
                self._row_selection.end_x,
            )

    @property
    def cursor(self) -> Any:
        return self._cursor

    @cursor.setter
    def cursor(self, value: Any) -> None:
        self._cursor = value

    @property
    def rows(self) -> list[Row]:
        return self._rows

    @rows.setter
    def rows(self, value: list[Row]) -> None:
        self._rows = value

    @property
    def selection(self) -> dict[int, tuple[int, int]]:
        return self._selection

    @property
    def rebuilt(self) -> int:
        return self._rebuilt

    @rebuilt.setter
    def rebuilt(self, value: int) -> None:
        self._rebuilt = value
