"""GhosttyTerminalView: drop-in for imgui_bundle.imgui_terminal.TerminalView.

Same surface: feed(bytes), on_input(bytes), on_resize(cols, rows),
render_in_child(id), title. Engine is libghostty-vt; rendering replays
cached per-row runs (FastGhosttyRows); input goes through Ghostty's encoders.

Single-threaded by design (Lux's loop): call feed() and render() from the
same thread. No lock.
"""

from __future__ import annotations

from collections.abc import Callable

from imgui_bundle import ImVec2, imgui
from pyghostty import Terminal, ffi, lib
from pyghostty._ffi import union_fn
from pyghostty.core import init_sized

from punt_lux.display.terminal.fast_rows import FastGhosttyRows
from punt_lux.display.terminal.ghostty_draw import u32
from punt_lux.display.terminal.ghostty_input import Input

# ghostty_terminal_scroll_viewport takes a tagged union by value (same twin as tilix2)
ffi.cdef(
    "typedef struct { uint32_t tag; uint32_t _pad; int64_t delta; int64_t _pad2; } ScrollVS;"
)
assert ffi.sizeof("ScrollVS") == ffi.sizeof("GhosttyTerminalScrollViewport")
_scroll_viewport = union_fn(
    "ghostty_terminal_scroll_viewport", "GhosttyResult(*)(GhosttyTerminal, ScrollVS)"
)

IV = ImVec2

# Same theme as imgui_terminal's default, so the two widgets are comparable.
THEME_FG, THEME_BG = (0xCC, 0xCC, 0xCC), (0x1E, 0x1E, 0x1E)
ANSI16 = [
    (0x00, 0x00, 0x00), (0xC2, 0x36, 0x21), (0x25, 0xBC, 0x24), (0xAD, 0xAD, 0x27),
    (0x49, 0x2E, 0xE1), (0xD3, 0x38, 0xD3), (0x33, 0xBB, 0xC8), (0xCB, 0xCC, 0xCD),
    (0x81, 0x83, 0x83), (0xFC, 0x39, 0x1F), (0x31, 0xE7, 0x22), (0xEA, 0xEC, 0x23),
    (0x58, 0x33, 0xFF), (0xF9, 0x35, 0xF8), (0x14, 0xF0, 0xF0), (0xE9, 0xEB, 0xEB),
]  # fmt: skip


def _set_palette(term: Terminal) -> None:
    """Override palette 0-15; keep Ghostty's default 16-255 (the xterm cube + greys)."""
    pal = ffi.new("GhosttyColorRgb[256]")
    lib.ghostty_terminal_get(term._t[0], lib.GHOSTTY_TERMINAL_DATA_COLOR_PALETTE, pal)
    for i, (r, g, b) in enumerate(ANSI16):
        pal[i].r, pal[i].g, pal[i].b = r, g, b
    lib.ghostty_terminal_set(term._t[0], lib.GHOSTTY_TERMINAL_OPT_COLOR_PALETTE, pal)


def _cell_size() -> tuple[float, float]:
    """(cell width, line height) in pixels for the current font at its current scale.

    Uses the glyph's real advance, NOT calc_text_size: ImGui rounds text sizes up to
    whole pixels, so with Lux's font_scale_main 1.1 a 7.5 px Inconsolata cell was
    measured as 8 px -- the cursor and run starts drifted 0.5 px per column from the
    text ImGui actually drew (cursor ~10 px off by column 20, ls -F columns ragged).
    """
    font = imgui.get_font()
    size = imgui.get_font_size()
    advance = font.get_font_baked(size).find_glyph(ord("M")).advance_x
    return advance, imgui.get_text_line_height()


class GhosttyTerminalView:
    def __init__(
        self,
        cols: int = 80,
        rows: int = 24,
        scrollback: int = 10_000,
        fixed: bool = False,
    ) -> None:
        self.fixed = fixed  # replay: keep the recording's size, don't fit to the window
        self.term = Terminal(
            cols, rows, scrollback=scrollback, fg=THEME_FG, bg=THEME_BG
        )
        _set_palette(self.term)
        self.term.on_reply(
            self._send
        )  # device-status / DA replies go back to the program
        self.rows = FastGhosttyRows(self.term)
        self.input = Input(self.term, self._send)
        self.on_input: Callable[[bytes], None] = lambda data: None
        self.on_resize: Callable[[int, int], None] = lambda cols, rows: None
        self._cols, self._rows = cols, rows
        self._sel_anchor: tuple[int, int] | None = (
            None  # screen coords (survive scrolling)
        )
        self.stats_ms = 0.0  # last render() Python time, for the HUD

    # -- data in / out ----------------------------------------------------
    def feed(self, data: bytes) -> None:
        if data:
            self.term.feed(data)

    def _send(self, data: bytes) -> None:
        self.on_input(data)

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows_n(self) -> int:
        return self._rows

    @property
    def title(self) -> str:
        buf = ffi.new("GhosttyString*")
        if lib.ghostty_terminal_get(
            self.term._t[0], lib.GHOSTTY_TERMINAL_DATA_TITLE, buf
        ):
            return ""
        return (
            ffi.buffer(buf.ptr, buf.len)[:].decode("utf-8", "replace")
            if buf.len
            else ""
        )

    # -- viewport ---------------------------------------------------------
    def scroll(self, tag: int, delta: int = 0) -> None:
        v = ffi.new("ScrollVS*")
        v.tag, v.delta = tag, delta
        _scroll_viewport(self.term._t[0], v[0])

    def _viewport_top(self) -> int:
        sb = ffi.new("GhosttyTerminalScrollbar*")
        lib.ghostty_terminal_get(
            self.term._t[0], lib.GHOSTTY_TERMINAL_DATA_SCROLLBAR, sb
        )
        return int(sb.offset)

    # -- rendering --------------------------------------------------------
    def render_in_child(
        self, str_id: str = "terminal", size: ImVec2 | None = None
    ) -> None:
        flags = (
            imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse
        )
        if imgui.begin_child(str_id, size or IV(0, 0), 0, flags):
            self.render()
        imgui.end_child()

    def render(self) -> None:
        import time

        t0 = time.perf_counter()
        cw, ch = _cell_size()
        avail = imgui.get_content_region_avail()
        self._maybe_resize(
            max(10, int(avail.x / cw)), max(3, int(avail.y / ch)), cw, ch
        )
        origin = imgui.get_cursor_screen_pos()
        focused = imgui.is_window_focused()
        hovered = imgui.is_window_hovered()
        if focused:
            self._handle_keys()
        if hovered or self._sel_anchor is not None:
            self._handle_mouse(origin, cw, ch, hovered)
        self.rows.update()
        self._draw(origin, cw, ch, focused)
        imgui.dummy(IV(self._cols * cw, self._rows * ch))
        self.stats_ms = (time.perf_counter() - t0) * 1e3

    def _maybe_resize(self, cols: int, rows: int, cw: float, ch: float) -> None:
        if self.fixed or (cols, rows) == (self._cols, self._rows):
            return
        self._cols, self._rows = cols, rows
        self.term.resize(cols, rows, int(cw), int(ch))
        self.on_resize(cols, rows)

    def _draw(self, origin: ImVec2, cw: float, ch: float, focused: bool) -> None:
        dl = imgui.get_window_draw_list()
        r = self.rows
        ox, oy = origin.x, origin.y
        # paint the whole visible child, not just the grid, so the terminal's extent is
        # obvious (the leftover sliver below/right of the grid is terminal, not window)
        wp, ws = imgui.get_window_pos(), imgui.get_window_size()
        dl.add_rect_filled(wp, IV(wp.x + ws.x, wp.y + ws.y), u32(r.bg))
        sel = self._selection_rows()
        for y, row in enumerate(r.rows):
            py = oy + y * ch
            for b in row.bgs:
                px = ox + b.x * cw
                dl.add_rect_filled(
                    IV(px, py), IV(px + b.ncells * cw, py + ch), u32(b.color)
                )
            if (span := sel.get(y)) is not None:
                x0, x1 = span
                dl.add_rect_filled(IV(ox + x0 * cw, py), IV(ox + (x1 + 1) * cw, py + ch),
                                   u32((90, 120, 200), 0x70))  # fmt: skip
            for run in row.runs:
                px = ox + run.x * cw
                dl.add_text(IV(px, py), u32(run.fg), run.text)
                if run.bold:  # cheap fake bold until a bold font is loaded
                    dl.add_text(IV(px + 0.6, py), u32(run.fg), run.text)
                if run.underline:
                    dl.add_line(IV(px, py + ch - 1), IV(px + run.ncells * cw, py + ch - 1),
                                u32(run.fg))  # fmt: skip
        c = r.cursor
        if c.visible and c.viewport_has_value:
            px, py = ox + c.viewport_x * cw, oy + c.viewport_y * ch
            style = c.visual_style
            col = u32(r.fg, 0xC0)
            if (
                not focused
                or style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BLOCK_HOLLOW
            ):
                dl.add_rect(IV(px, py), IV(px + cw, py + ch), col)
            elif style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_BAR:
                dl.add_rect_filled(IV(px, py), IV(px + 2, py + ch), col)
            elif style == lib.GHOSTTY_RENDER_STATE_CURSOR_VISUAL_STYLE_UNDERLINE:
                dl.add_rect_filled(IV(px, py + ch - 2), IV(px + cw, py + ch), col)
            else:
                dl.add_rect_filled(IV(px, py), IV(px + cw, py + ch), u32(r.fg, 0x90))

    # -- input ------------------------------------------------------------
    def _handle_keys(self) -> None:
        io = imgui.get_io()
        clip = (
            io.key_ctrl
            if io.config_mac_osx_behaviors
            else (io.key_ctrl and io.key_shift)
        )
        if clip and imgui.is_key_pressed(imgui.Key.c):
            if text := self.selected_text():
                imgui.set_clipboard_text(text)
            return
        if clip and imgui.is_key_pressed(imgui.Key.v):
            self.input.paste(imgui.get_clipboard_text() or "")
            return
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_up):
            self.scroll(lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, -self._rows // 2)
            return
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_down):
            self.scroll(lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, self._rows // 2)
            return
        if self.input.poll_keyboard():
            self._set_selection(None)
            if not self.term.get("viewport_active", "bool"):
                self.scroll(
                    lib.GHOSTTY_SCROLL_VIEWPORT_BOTTOM
                )  # typing snaps to the live view

    def _cell(self, origin: ImVec2, cw: float, ch: float) -> tuple[int, int]:
        mp = imgui.get_mouse_pos()
        x = min(self._cols - 1, max(0, int((mp.x - origin.x) // cw)))
        y = min(self._rows - 1, max(0, int((mp.y - origin.y) // ch)))
        return x, y

    def _handle_mouse(
        self, origin: ImVec2, cw: float, ch: float, hovered: bool
    ) -> None:
        mp = imgui.get_mouse_pos()
        if hovered and self.input.app_wants_mouse():
            self.input.poll_mouse(
                mp.x - origin.x, mp.y - origin.y, cw, ch, self._cols, self._rows
            )
            return
        left = imgui.MouseButton_.left
        if hovered and (wheel := imgui.get_io().mouse_wheel):
            screen = lib.GHOSTTY_TERMINAL_DATA_ACTIVE_SCREEN
            alt = ffi.new("int*")
            lib.ghostty_terminal_get(self.term._t[0], screen, alt)
            if alt[0] == lib.GHOSTTY_TERMINAL_SCREEN_ALTERNATE and self.term.mode(1007):
                key = (
                    lib.GHOSTTY_KEY_ARROW_UP
                    if wheel > 0
                    else lib.GHOSTTY_KEY_ARROW_DOWN
                )
                for _ in range(3):  # less/man without mouse: wheel -> arrows
                    self.input.key(key, 0, None, lib.GHOSTTY_KEY_ACTION_PRESS)
            else:
                self.scroll(lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, -3 if wheel > 0 else 3)
        if hovered and imgui.is_mouse_clicked(left):
            x, y = self._cell(origin, cw, ch)
            n = imgui.get_mouse_clicked_count(left)
            if n >= 2:
                self._select_unit(x, y, line=n >= 3)
                self._sel_anchor = None
            else:
                self._sel_anchor = (x, y + self._viewport_top())
                self._set_selection(None)
        elif self._sel_anchor is not None and imgui.is_mouse_down(left):
            x, y = self._cell(origin, cw, ch)
            my = imgui.get_mouse_pos().y
            if my < origin.y:  # drag past the edge: autoscroll
                self.scroll(lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, -1)
            elif my > origin.y + self._rows * ch:
                self.scroll(lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, 1)
            end = (x, y + self._viewport_top())
            if end != self._sel_anchor:
                self._set_selection(self._sel_anchor, end, "screen")
        if imgui.is_mouse_released(left):
            self._sel_anchor = None

    # -- selection (owned by Ghostty: it tracks the selection while scrolling) --
    def _set_selection(
        self,
        a: tuple[int, int] | None,
        b: tuple[int, int] | None = None,
        tag: str = "viewport",
    ) -> None:
        sel = ffi.NULL
        if a is not None:
            sel = init_sized("GhosttySelection")
            sel.start = self.term.ref(*a, tag)[0]
            sel.end = self.term.ref(*(b or a), tag)[0]
        lib.ghostty_terminal_set(
            self.term._t[0], lib.GHOSTTY_TERMINAL_OPT_SELECTION, sel
        )

    def _select_unit(self, x: int, y: int, line: bool) -> None:
        sel = init_sized("GhosttySelection")
        kind = "Line" if line else "Word"
        opts = init_sized(
            f"GhosttyTerminalSelect{kind}Options"
        )  # NULL lists = Ghostty defaults
        opts.ref = self.term.ref(x, y, "viewport")[0]
        fn = (
            lib.ghostty_terminal_select_line
            if line
            else lib.ghostty_terminal_select_word
        )
        if fn(self.term._t[0], opts, sel) == 0:
            lib.ghostty_terminal_set(
                self.term._t[0], lib.GHOSTTY_TERMINAL_OPT_SELECTION, sel
            )

    def selected_text(self) -> str:
        sel = init_sized("GhosttySelection")
        if lib.ghostty_terminal_get(
            self.term._t[0], lib.GHOSTTY_TERMINAL_DATA_SELECTION, sel
        ):
            return ""
        return self.term._format_sel(sel, unwrap=True)

    def _selection_rows(self) -> dict[int, tuple[int, int]]:
        """Viewport row -> (x0, x1) of the selection, from the render state."""
        return self.rows.selection
