# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""``TerminalView``: the terminal widget for an ImGui window.

It has the same surface as ``imgui_bundle.imgui_terminal.TerminalView``, so
the two are interchangeable: ``feed(bytes)``, the ``on_input`` and
``on_resize`` callbacks, ``render_in_child(id)`` and ``title``. Where the
bytes come from (a local PTY, a daemon, a replay) is the caller's business.

Per frame, ``render()``:

1. measures the cell from the current font and fits the grid to the space;
2. routes keyboard input (when focused) and mouse input (when hovered);
3. syncs the render state, rebuilding only dirty rows;
4. paints rows, selection and cursor.

Single-threaded by design: ``feed`` and ``render`` must be called from the
same thread (the Display's render thread). There is no lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.ffi import (
    Terminal,
    ffi,
    handle,
    lib,
    scroll_viewport,
    string_value,
)
from punt_lux.display.terminal.input import Input, MouseFrame
from punt_lux.display.terminal.model import RGB
from punt_lux.display.terminal.painter import CellGrid, Painter
from punt_lux.display.terminal.render_state import RenderState
from punt_lux.display.terminal.selection import Selection

__all__ = ["TerminalView"]

MIN_COLS, MIN_ROWS = 10, 3
WHEEL_SCROLL_LINES = 3

# imgui_terminal's default theme, so the two widgets can be compared directly.
THEME_FG: RGB = (0xCC, 0xCC, 0xCC)
THEME_BG: RGB = (0x1E, 0x1E, 0x1E)
ANSI16: tuple[RGB, ...] = (
    (0x00, 0x00, 0x00), (0xC2, 0x36, 0x21), (0x25, 0xBC, 0x24), (0xAD, 0xAD, 0x27),
    (0x49, 0x2E, 0xE1), (0xD3, 0x38, 0xD3), (0x33, 0xBB, 0xC8), (0xCB, 0xCC, 0xCD),
    (0x81, 0x83, 0x83), (0xFC, 0x39, 0x1F), (0x31, 0xE7, 0x22), (0xEA, 0xEC, 0x23),
    (0x58, 0x33, 0xFF), (0xF9, 0x35, 0xF8), (0x14, 0xF0, 0xF0), (0xE9, 0xEB, 0xEB),
)  # fmt: skip


class TerminalView:
    """A Ghostty terminal drawn and driven inside the current ImGui window."""

    def __init__(
        self,
        cols: int = 80,
        rows: int = 24,
        *,
        scrollback: int = 10_000,
        fixed_size: bool = False,
    ) -> None:
        self.term = Terminal(
            cols, rows, scrollback=scrollback, fg=THEME_FG, bg=THEME_BG
        )
        _apply_palette(self.term, ANSI16)
        self.term.on_reply(self._send)  # replies to queries (DA, DSR) go to the program
        self.state = RenderState(self.term)
        self.input = Input(self.term, self._send)
        self.selection = Selection(self.term)
        self.on_input: Callable[[bytes], None] = lambda _data: None
        self.on_resize: Callable[[int, int], None] = lambda _cols, _rows: None
        self.fixed_size = fixed_size  # replays: keep the recorded size
        self._cols, self._rows = cols, rows
        self._painter = Painter()
        self.render_ms = 0.0  # Python time of the last render(), for diagnostics

    # -- data ----------------------------------------------------------------
    def feed(self, data: bytes) -> None:
        """Process output from the program."""
        if data:
            self.term.feed(data)

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def title(self) -> str:
        """The window title the program set (OSC 0/2), or ''."""
        return string_value(self.term, lib.GHOSTTY_TERMINAL_DATA_TITLE)

    def _send(self, data: bytes) -> None:
        self.on_input(data)

    # -- frame ---------------------------------------------------------------
    def render_in_child(
        self, str_id: str = "terminal", size: ImVec2 | None = None
    ) -> None:
        """Render inside a child window (the recommended embedding)."""
        # no_nav_inputs: ImGui's built-in Tab focus-cycling runs even without
        # NavEnableKeyboard, and would take Tab (shell completion) away from
        # the program and move focus out of the terminal.
        flags = (
            imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_scroll_with_mouse
            | imgui.WindowFlags_.no_nav_inputs
        )
        if imgui.begin_child(str_id, size or ImVec2(0, 0), 0, flags):
            self.render()
        imgui.end_child()

    def render(self) -> None:
        """Fit, handle input, update and paint, in the current window."""
        started = time.perf_counter()
        grid = CellGrid.for_current_font(imgui.get_cursor_screen_pos())
        avail = imgui.get_content_region_avail()
        self._fit(int(avail.x / grid.cell_w), int(avail.y / grid.cell_h), grid)
        focused = imgui.is_window_focused()
        hovered = imgui.is_window_hovered()
        if focused:
            self._handle_keys()
        if hovered or self.selection.dragging:
            self._handle_mouse(grid, hovered=hovered)
        self.state.update()
        self._painter.paint(self.state, grid, focused=focused)
        imgui.dummy(ImVec2(self._cols * grid.cell_w, self._rows * grid.cell_h))
        self.render_ms = (time.perf_counter() - started) * 1e3

    def _fit(self, cols: int, rows: int, grid: CellGrid) -> None:
        cols, rows = max(MIN_COLS, cols), max(MIN_ROWS, rows)
        if self.fixed_size or (cols, rows) == (self._cols, self._rows):
            return
        self._cols, self._rows = cols, rows
        self.term.resize(cols, rows, int(grid.cell_w), int(grid.cell_h))
        self.on_resize(cols, rows)

    # -- keyboard ------------------------------------------------------------
    def _handle_keys(self) -> None:
        """Clipboard and scrollback shortcuts first; everything else to the program."""
        io = imgui.get_io()
        # Cmd+C/V on macOS (ImGui reports Cmd as key_ctrl there);
        # Ctrl+Shift+C/V elsewhere.
        clip = (
            io.key_ctrl
            if io.config_mac_osx_behaviors
            else (io.key_ctrl and io.key_shift)
        )
        if clip and imgui.is_key_pressed(imgui.Key.c):
            if text := self.selection.text():
                imgui.set_clipboard_text(text)
            return
        if clip and imgui.is_key_pressed(imgui.Key.v):
            self.input.paste(imgui.get_clipboard_text() or "")
            return
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_up):
            self._scroll_by(-self._rows // 2)
            return
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_down):
            self._scroll_by(self._rows // 2)
            return
        if self.input.poll_keyboard():
            self.selection.clear()
            if not self.term.get("viewport_active", "bool"):
                scroll_viewport(self.term, lib.GHOSTTY_SCROLL_VIEWPORT_BOTTOM)

    # -- mouse ---------------------------------------------------------------
    def _handle_mouse(self, grid: CellGrid, *, hovered: bool) -> None:
        mouse = imgui.get_mouse_pos()
        if hovered and self.input.program_wants_mouse():
            self.input.poll_mouse(
                MouseFrame(
                    mouse.x - grid.origin.x,
                    mouse.y - grid.origin.y,
                    grid.cell_w,
                    grid.cell_h,
                    self._cols,
                    self._rows,
                )
            )
            return
        if hovered and (wheel := imgui.get_io().mouse_wheel):
            self._wheel(wheel)
        self._select_with_mouse(grid, mouse, hovered=hovered)

    def _wheel(self, wheel: float) -> None:
        """Scroll back, or send arrows to an alternate-screen program (xterm 1007)."""
        if self._on_alternate_screen() and self.term.mode(1007):
            key = lib.GHOSTTY_KEY_ARROW_UP if wheel > 0 else lib.GHOSTTY_KEY_ARROW_DOWN
            for _ in range(WHEEL_SCROLL_LINES):
                self.input.key(key, 0, None, lib.GHOSTTY_KEY_ACTION_PRESS)
        else:
            self._scroll_by(-WHEEL_SCROLL_LINES if wheel > 0 else WHEEL_SCROLL_LINES)

    def _select_with_mouse(
        self, grid: CellGrid, mouse: ImVec2, *, hovered: bool
    ) -> None:
        left = imgui.MouseButton_.left
        col, row = grid.cell_at(mouse.x, mouse.y, self._cols, self._rows)
        if hovered and imgui.is_mouse_clicked(left):
            clicks = imgui.get_mouse_clicked_count(left)
            if clicks >= 3:
                self.selection.select_line((col, row))
            elif clicks == 2:
                self.selection.select_word((col, row))
            else:
                self.selection.start_drag((col, row + self._viewport_top()))
        elif self.selection.dragging and imgui.is_mouse_down(left):
            if mouse.y < grid.origin.y:  # dragging past an edge scrolls
                self._scroll_by(-1)
            elif mouse.y > grid.origin.y + self._rows * grid.cell_h:
                self._scroll_by(1)
            self.selection.extend_drag((col, row + self._viewport_top()))
        if imgui.is_mouse_released(left):
            self.selection.end_drag()

    # -- viewport ------------------------------------------------------------
    def _scroll_by(self, rows: int) -> None:
        scroll_viewport(self.term, lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, rows)

    def _viewport_top(self) -> int:
        """Rows of scrollback above the viewport (viewport row + this = screen row)."""
        bar = ffi.new("GhosttyTerminalScrollbar*")
        lib.ghostty_terminal_get(
            handle(self.term), lib.GHOSTTY_TERMINAL_DATA_SCROLLBAR, bar
        )
        return int(bar.offset)

    def _on_alternate_screen(self) -> bool:
        screen = ffi.new("int*")
        lib.ghostty_terminal_get(
            handle(self.term), lib.GHOSTTY_TERMINAL_DATA_ACTIVE_SCREEN, screen
        )
        return bool(screen[0] == lib.GHOSTTY_TERMINAL_SCREEN_ALTERNATE)


def _apply_palette(term: Terminal, colors: tuple[RGB, ...]) -> None:
    """Override palette entries 0-15; keep Ghostty's 16-255 (xterm cube, greys)."""
    palette = ffi.new("GhosttyColorRgb[256]")
    lib.ghostty_terminal_get(
        handle(term), lib.GHOSTTY_TERMINAL_DATA_COLOR_PALETTE, palette
    )
    for i, (r, g, b) in enumerate(colors):
        palette[i].r, palette[i].g, palette[i].b = r, g, b
    lib.ghostty_terminal_set(
        handle(term), lib.GHOSTTY_TERMINAL_OPT_COLOR_PALETTE, palette
    )
