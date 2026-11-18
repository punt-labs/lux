# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""Draw a ``RenderState`` into the current ImGui window's draw list.

Pure drawing: no input, no terminal mutation. The grid geometry
(``CellGrid``) is computed once per frame by the view and passed in, so the
painter, the mouse code and the cursor all agree on where a cell is
(ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.model import RGB
from punt_lux.display.terminal.render_state import RenderState
from punt_lux.terminal.ffi import lib

__all__ = ["CellGrid", "Painter", "rgba"]

SELECTION_TINT: RGB = (90, 120, 200)
SELECTION_ALPHA = 0x70
FAKE_BOLD_OFFSET = 0.6  # px; double-strike until a bold face is loaded


def rgba(color: RGB, alpha: int = 0xFF) -> int:
    """Pack an RGB colour into ImGui's ABGR ``ImU32``."""
    r, g, b = color
    return (alpha << 24) | (b << 16) | (g << 8) | r


@dataclass(frozen=True, slots=True)
class CellGrid:
    """Where the grid is on screen this frame, in pixels."""

    origin: ImVec2
    cell_w: float
    cell_h: float

    @classmethod
    def for_current_font(cls, origin: ImVec2) -> CellGrid:
        """Measure the cell from the font ImGui is using right now.

        Uses the glyph's real advance, not ``calc_text_size``: ImGui rounds
        text sizes up to whole pixels, so under Lux's ``font_scale_main`` of
        1.1 a 7.5 px Inconsolata cell measured as 8 px. Text was drawn at
        7.5 px per column while the cursor and run starts used 8 px, a drift
        of 0.5 px per column (cursor ~10 px off by column 20; ``ls -F``
        columns ragged). See STEP3.md.
        """
        size = imgui.get_font_size()
        glyph = imgui.get_font().get_font_baked(size).find_glyph(ord("M"))
        return cls(origin, glyph.advance_x, imgui.get_text_line_height())

    def cell_at(self, x: float, y: float, cols: int, rows: int) -> tuple[int, int]:
        """The (column, row) under screen point (x, y), clamped to the grid."""
        col = int((x - self.origin.x) // self.cell_w)
        row = int((y - self.origin.y) // self.cell_h)
        return min(cols - 1, max(0, col)), min(rows - 1, max(0, row))

    def top_left(self, col: float, row: float) -> ImVec2:
        return ImVec2(
            self.origin.x + col * self.cell_w, self.origin.y + row * self.cell_h
        )


class Painter:
    """Replays the cached rows, then the selection tint and the cursor."""

    def paint(self, state: RenderState, grid: CellGrid, *, focused: bool) -> None:
        dl = imgui.get_window_draw_list()
        self._fill_window(dl, state.bg)
        for y, row in enumerate(state.rows):
            for span in row.bgs:
                self._rect(dl, grid, span.x, y, span.ncells, rgba(span.color))
            if (sel := state.selection.get(y)) is not None:
                x0, x1 = sel
                self._rect(
                    dl, grid, x0, y, x1 - x0 + 1, rgba(SELECTION_TINT, SELECTION_ALPHA)
                )
            for run in row.runs:
                pos, col = grid.top_left(run.x, y), rgba(run.fg)
                dl.add_text(pos, col, run.text)
                if run.bold:
                    dl.add_text(ImVec2(pos.x + FAKE_BOLD_OFFSET, pos.y), col, run.text)
                if run.underline:
                    base = pos.y + grid.cell_h - 1
                    end = pos.x + run.ncells * grid.cell_w
                    dl.add_line(ImVec2(pos.x, base), ImVec2(end, base), col)
        self._cursor(dl, state, grid, focused=focused)

    @staticmethod
    def _fill_window(dl: imgui.ImDrawList, bg: RGB) -> None:
        """Paint the whole child, so the terminal's extent is visible (STEP2.md)."""
        pos, size = imgui.get_window_pos(), imgui.get_window_size()
        dl.add_rect_filled(pos, ImVec2(pos.x + size.x, pos.y + size.y), rgba(bg))

    @staticmethod
    def _rect(
        dl: imgui.ImDrawList, grid: CellGrid, x: int, y: int, ncells: int, col: int
    ) -> None:
        tl = grid.top_left(x, y)
        dl.add_rect_filled(
            tl, ImVec2(tl.x + ncells * grid.cell_w, tl.y + grid.cell_h), col
        )

    @staticmethod
    def _cursor(
        dl: imgui.ImDrawList, state: RenderState, grid: CellGrid, *, focused: bool
    ) -> None:
        cur = state.cursor
        if not (cur.visible and cur.viewport_has_value):
            return
        tl = grid.top_left(cur.viewport_x, cur.viewport_y)
        w, h = grid.cell_w, grid.cell_h
        col = rgba(state.fg, 0xC0)
        style = cur.visual_style
        if (
            not focused
            or style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BLOCK_HOLLOW
        ):
            dl.add_rect(tl, ImVec2(tl.x + w, tl.y + h), col)  # unfocused: outline
        elif style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BAR:
            dl.add_rect_filled(tl, ImVec2(tl.x + 2, tl.y + h), col)
        elif style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_UNDERLINE:
            dl.add_rect_filled(
                ImVec2(tl.x, tl.y + h - 2), ImVec2(tl.x + w, tl.y + h), col
            )
        else:
            dl.add_rect_filled(tl, ImVec2(tl.x + w, tl.y + h), rgba(state.fg, 0x90))
