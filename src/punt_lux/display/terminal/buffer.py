"""Owned native terminal, encoders, selection and render cache behind a view."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self

from punt_lux.display.terminal.clipboard import ClipboardActions
from punt_lux.display.terminal.input import Input, MouseFrame
from punt_lux.display.terminal.render_state import RenderState
from punt_lux.display.terminal.selection import Selection
from punt_lux.display.terminal.theme import TerminalTheme
from punt_lux.terminal.ffi import Terminal
from punt_lux.terminal.ffi_terminal import TerminalIO

__all__ = [
    "Input",
    "MouseFrame",
    "RenderState",
    "Selection",
    "Terminal",
    "TerminalBuffer",
]


class TerminalBuffer:
    """A replaceable replica; each buffer owns and releases its native resources."""

    _io: TerminalIO
    _state: RenderState
    _input: Input
    _selection: Selection
    _clipboard: ClipboardActions
    _closed: bool

    def __new__(cls, term: Terminal, write: Callable[[bytes], None]) -> Self:
        self = super().__new__(cls)
        self._io = TerminalIO(term)
        self._state = RenderState(term)
        self._input = Input(term, write)
        self._selection = Selection(term)
        self._clipboard = ClipboardActions(self._input, self._selection)
        self._closed = False
        return self

    @classmethod
    def local(
        cls,
        cols: int,
        rows: int,
        scrollback: int,
        write: Callable[[bytes], None],
    ) -> Self:
        term = Terminal(
            cols, rows, scrollback=scrollback, fg=TerminalTheme.FG, bg=TerminalTheme.BG
        )
        TerminalTheme.apply(term)
        buffer = cls(term, write)
        buffer._io.on_reply(write)
        return buffer

    @property
    def term(self) -> Terminal:
        return self._io.native

    @property
    def state(self) -> RenderState:
        return self._state

    @property
    def input(self) -> Input:
        return self._input

    @property
    def selection(self) -> Selection:
        return self._selection

    @property
    def size(self) -> tuple[int, int]:
        return self._io.size

    def feed(self, data: bytes) -> None:
        self._io.feed(data)

    def resize(self, cols: int, rows: int) -> None:
        self._io.resize(cols, rows)

    def clipboard(self) -> bool:
        return self._clipboard.handle()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._input.close()
            self._state.close()
            self._io.close()
