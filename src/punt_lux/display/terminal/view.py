# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""``TerminalView``: the terminal widget for an ImGui window.

It has the same surface as ``imgui_bundle.imgui_terminal.TerminalView``, so
the two are interchangeable: ``feed(bytes)``, the ``on_input`` and
``on_resize`` callbacks, ``render_in_child(id)`` and ``title``. Where the
bytes come from (a local PTY, a daemon, a replay) is the caller's business.

Per frame, ``render()`` fits the grid within the wire's 1024x512-cell limit,
routes focused/hovered input, rebuilds dirty rows and paints the grid.

Single-threaded by design: ``feed`` and ``render`` must be called from the
same thread (the Display's render thread). There is no lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Self

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.buffer import (
    Input,
    MouseFrame,
    RenderState,
    Selection,
    TerminalBuffer,
    TerminalTheme,
)
from punt_lux.display.terminal.painter import CellGrid, Painter
from punt_lux.display.terminal.sizing import ViewSizing
from punt_lux.terminal.ffi import (
    Terminal,
    ffi,
    handle,
    lib,
    scroll_viewport,
    string_value,
)

__all__ = ["TerminalView"]

MIN_COLS, MIN_ROWS = 10, 3
MAX_COLS, MAX_ROWS = 1024, 512
WHEEL_SCROLL_LINES = 3


class TerminalView:
    """A Ghostty terminal drawn and driven inside the current ImGui window."""

    _buffer: TerminalBuffer
    _on_input: Callable[[bytes], None]
    _on_resize: Callable[[int, int], None]
    _sizing: ViewSizing
    _painter: Painter
    _render_ms: float
    _closed: bool

    def __new__(
        cls,
        cols: int = 80,
        rows: int = 24,
        *,
        scrollback: int = 10_000,
        fixed_size: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        self._buffer = TerminalBuffer.local(cols, rows, scrollback, self._send)
        self._on_input = lambda _data: None
        self._on_resize = lambda _cols, _rows: None
        self._sizing = ViewSizing((cols, rows), fixed=fixed_size)
        self._painter = Painter()
        self._render_ms = 0.0  # Python time of the last render(), for diagnostics
        self._closed = False
        return self

    def close(self) -> None:
        """Release native render and input resources once."""
        if self._closed:
            return
        self._closed = True
        self._buffer.close()

    def adopt(self, term: Terminal) -> None:
        """Install a daemon snapshot; replicas never answer program queries."""
        replacement = TerminalBuffer(term, self._send)
        self._buffer.close()
        self._buffer = replacement
        self._sizing.adopt(replacement.size)

    def resize_from_daemon(self, cols: int, rows: int) -> None:
        self._buffer.resize(cols, rows)
        self._sizing.accept((cols, rows))

    # -- data ----------------------------------------------------------------
    def feed(self, data: bytes) -> None:
        """Process output from the program."""
        if data:
            self._buffer.feed(data)

    @property
    def size(self) -> tuple[int, int]:
        return self._sizing.actual[0], self._sizing.actual[1]

    @property
    def cols(self) -> int:
        return self._sizing.actual[0]

    @property
    def rows(self) -> int:
        return self._sizing.actual[1]

    @property
    def title(self) -> str:
        """The window title the program set (OSC 0/2), or ''."""
        return string_value(self._buffer.term, lib.GHOSTTY_TERMINAL_DATA_TITLE)

    def _send(self, data: bytes) -> None:
        self._on_input(data)

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
        self._fit(int(avail.x / grid.cell_w), int(avail.y / grid.cell_h))
        focused = imgui.is_window_focused()
        hovered = imgui.is_window_hovered()
        if focused:
            self._handle_keys()
        captured = self._buffer.input.mouse_captured
        if any((hovered, self._buffer.selection.dragging, captured)):
            self._handle_mouse(grid, hovered=hovered)
        self._buffer.state.update()
        self._painter.paint(self._buffer.state, grid, focused=focused)
        imgui.dummy(
            ImVec2(
                self._sizing.actual[0] * grid.cell_w,
                self._sizing.actual[1] * grid.cell_h,
            )
        )
        self._render_ms = (time.perf_counter() - started) * 1e3

    def _fit(self, cols: int, rows: int) -> None:
        cols = min(MAX_COLS, max(MIN_COLS, cols))
        rows = min(MAX_ROWS, max(MIN_ROWS, rows))
        result = self._sizing.fit((cols, rows))
        if result == "local":
            self._buffer.resize(cols, rows)
        if result != "none":
            self._on_resize(cols, rows)

    # -- keyboard ------------------------------------------------------------
    def _handle_keys(self) -> None:
        """Clipboard and scrollback shortcuts first; everything else to the program."""
        if self._clipboard_shortcut():
            return
        io = imgui.get_io()
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_up):
            self._scroll_by(-self._sizing.actual[1] // 2)
            return
        if io.key_shift and imgui.is_key_pressed(imgui.Key.page_down):
            self._scroll_by(self._sizing.actual[1] // 2)
            return
        if self._buffer.input.poll_keyboard():
            self._buffer.selection.clear()
            if not self._buffer.term.get("viewport_active", "bool"):
                scroll_viewport(self._buffer.term, lib.GHOSTTY_SCROLL_VIEWPORT_BOTTOM)

    def _clipboard_shortcut(self) -> bool:
        return self._buffer.clipboard()

    # -- mouse ---------------------------------------------------------------
    def _handle_mouse(self, grid: CellGrid, *, hovered: bool) -> None:
        mouse = imgui.get_mouse_pos()
        if self._buffer.input.program_wants_mouse(hovered=hovered):
            self._buffer.input.poll_mouse(
                MouseFrame.at_pointer(
                    grid.origin,
                    (grid.cell_w, grid.cell_h),
                    self._sizing.actual,
                )
            )
            return
        if hovered and (wheel := imgui.get_io().mouse_wheel):
            self._wheel(wheel)
        self._select_with_mouse(grid, mouse, hovered=hovered)

    def _wheel(self, wheel: float) -> None:
        """Scroll back, or send arrows to an alternate-screen program (xterm 1007)."""
        if self._on_alternate_screen() and self._buffer.term.mode(1007):
            key = lib.GHOSTTY_KEY_ARROW_UP if wheel > 0 else lib.GHOSTTY_KEY_ARROW_DOWN
            for _ in range(WHEEL_SCROLL_LINES):
                self._buffer.input.key(key, 0, None, lib.GHOSTTY_KEY_ACTION_PRESS)
        else:
            self._scroll_by(-WHEEL_SCROLL_LINES if wheel > 0 else WHEEL_SCROLL_LINES)

    def _select_with_mouse(
        self, grid: CellGrid, mouse: ImVec2, *, hovered: bool
    ) -> None:
        left = imgui.MouseButton_.left
        col, row = grid.cell_at(
            mouse.x, mouse.y, self._sizing.actual[0], self._sizing.actual[1]
        )
        if hovered and imgui.is_mouse_clicked(left):
            clicks = imgui.get_mouse_clicked_count(left)
            if clicks >= 3:
                self._buffer.selection.select_line((col, row))
            elif clicks == 2:
                self._buffer.selection.select_word((col, row))
            else:
                self._buffer.selection.start_drag((col, row + self._viewport_top()))
        elif self._buffer.selection.dragging and imgui.is_mouse_down(left):
            if mouse.y < grid.origin.y:  # dragging past an edge scrolls
                self._scroll_by(-1)
            elif mouse.y > grid.origin.y + self._sizing.actual[1] * grid.cell_h:
                self._scroll_by(1)
            self._buffer.selection.extend_drag((col, row + self._viewport_top()))
        if imgui.is_mouse_released(left):
            self._buffer.selection.end_drag()

    # -- viewport ------------------------------------------------------------
    def _scroll_by(self, rows: int) -> None:
        scroll_viewport(self._buffer.term, lib.GHOSTTY_SCROLL_VIEWPORT_DELTA, rows)

    def _viewport_top(self) -> int:
        """Rows of scrollback above the viewport (viewport row + this = screen row)."""
        bar = ffi.new("GhosttyTerminalScrollbar*")
        lib.ghostty_terminal_get(
            handle(self._buffer.term), lib.GHOSTTY_TERMINAL_DATA_SCROLLBAR, bar
        )
        return int(bar.offset)

    def _on_alternate_screen(self) -> bool:
        screen = ffi.new("int*")
        lib.ghostty_terminal_get(
            handle(self._buffer.term), lib.GHOSTTY_TERMINAL_DATA_ACTIVE_SCREEN, screen
        )
        return bool(screen[0] == lib.GHOSTTY_TERMINAL_SCREEN_ALTERNATE)

    @property
    def term(self) -> Terminal:
        return self._buffer.term

    @property
    def state(self) -> RenderState:
        return self._buffer.state

    @property
    def input(self) -> Input:
        return self._buffer.input

    @property
    def selection(self) -> Selection:
        return self._buffer.selection

    @property
    def on_input(self) -> Callable[[bytes], None]:
        return self._on_input

    @on_input.setter
    def on_input(self, value: Callable[[bytes], None]) -> None:
        self._on_input = value

    @property
    def on_resize(self) -> Callable[[int, int], None]:
        return self._on_resize

    @on_resize.setter
    def on_resize(self, value: Callable[[int, int], None]) -> None:
        self._on_resize = value

    @property
    def fixed_size(self) -> bool:
        return self._sizing.fixed

    @fixed_size.setter
    def fixed_size(self, value: bool) -> None:
        self._sizing.fixed = value

    @property
    def render_ms(self) -> float:
        return self._render_ms

    @render_ms.setter
    def render_ms(self, value: float) -> None:
        self._render_ms = value


THEME_FG = TerminalTheme.FG
THEME_BG = TerminalTheme.BG
ANSI16 = TerminalTheme.ANSI16
