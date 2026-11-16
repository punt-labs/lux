"""The two engines under test, behind one tiny interface for the benchmark.

- GhosttyEngine: pyghostty + GhosttyRows (dirty-row cache) + draw_rows.
- PyteEngine: imgui_bundle.imgui_terminal.TerminalView, the existing widget,
  driven through its own feed() and _draw() so we measure exactly what ships.
"""

from __future__ import annotations

from typing import Protocol

from imgui_bundle import ImVec2, imgui
from pyghostty import Terminal

from fast_rows import FastGhosttyRows
from ghostty_draw import draw_rows
from ghostty_rows import GhosttyRows


class Engine(Protocol):
    name: str

    def feed(self, data: bytes) -> None: ...
    def prepare(self) -> int: ...  # per-frame state sync; returns rows rebuilt (-1 = n/a)
    def draw(self, cw: float, ch: float) -> None: ...
    def text(self) -> str: ...


class GhosttyEngine:
    name = "ghostty"

    def __init__(self, cols: int, rows: int, fast: bool = False) -> None:
        self.term = Terminal(cols, rows, scrollback=5000)
        self.rows = (FastGhosttyRows if fast else GhosttyRows)(self.term)

    def feed(self, data: bytes) -> None:
        if data:
            self.term.feed(data)

    def prepare(self) -> int:
        return self.rows.update()

    def draw(self, cw: float, ch: float) -> None:
        draw_rows(self.rows, imgui.get_cursor_screen_pos(), cw, ch)

    def text(self) -> str:
        return self.term.text()


class PyteEngine:
    name = "pyte"

    def __init__(self, cols: int, rows: int) -> None:
        from imgui_bundle.imgui_terminal import TerminalView

        self.view = TerminalView(cols, rows, history=5000)
        self.view._maybe_resize = lambda c, r: None  # type: ignore[method-assign,assignment]  # fixed size

    def feed(self, data: bytes) -> None:
        if data:
            self.view.feed(data)

    def prepare(self) -> int:
        return -1  # pyte has no dirty tracking: _draw rebuilds every visible row

    def draw(self, cw: float, ch: float) -> None:
        self.view._draw(cw, ch)

    def text(self) -> str:
        return "\n".join(self.view.screen.display)


def make(name: str, cols: int, rows: int) -> Engine:
    if name == "pyte":
        return PyteEngine(cols, rows)
    eng = GhosttyEngine(cols, rows, fast=name == "ghostty-fast")
    eng.name = name
    return eng


__all__ = ["Engine", "ImVec2", "make"]
