# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""Text selection, owned by Ghostty.

Ghostty stores the selection as tracked references into the screen, so it
stays on the right text while output scrolls, and it formats the selected
text (soft-wrapped lines joined, trailing spaces trimmed). The widget only
turns mouse gestures into selection calls; it doesn't track a range itself.
"""

from __future__ import annotations

from typing import Self

from punt_lux.terminal.ffi import Terminal, ffi, handle, init_sized, lib

__all__ = ["Selection"]

Cell = tuple[int, int]  # (column, row)


class Selection:
    """Drag, word and line selection for one terminal."""

    _term: Terminal
    _anchor: Cell | None

    def __new__(cls, term: Terminal) -> Self:
        self = super().__new__(cls)
        self._term = term
        self._anchor = None  # screen coordinates: survive scrolling
        return self

    @property
    def dragging(self) -> bool:
        return self._anchor is not None

    def start_drag(self, at_screen: Cell) -> None:
        """Begin a drag at a screen cell; clears any existing selection."""
        self._anchor = at_screen
        self.clear()

    def extend_drag(self, to_screen: Cell) -> None:
        if self._anchor is not None and to_screen != self._anchor:
            self._set(self._anchor, to_screen, "screen")

    def end_drag(self) -> None:
        self._anchor = None

    def select_word(self, at_viewport: Cell) -> None:
        self._select_unit("Word", lib.ghostty_terminal_select_word, at_viewport)

    def select_line(self, at_viewport: Cell) -> None:
        self._select_unit("Line", lib.ghostty_terminal_select_line, at_viewport)

    def clear(self) -> None:
        lib.ghostty_terminal_set(
            handle(self._term), lib.GHOSTTY_TERMINAL_OPT_SELECTION, ffi.NULL
        )

    def text(self) -> str:
        """The selected text, soft-wrapped lines joined; '' with no selection."""
        sel = init_sized("GhosttySelection")
        if lib.ghostty_terminal_get(
            handle(self._term), lib.GHOSTTY_TERMINAL_DATA_SELECTION, sel
        ):
            return ""
        text: str = self._term._format_sel(sel, unwrap=True)
        return text

    def _set(self, start: Cell, end: Cell, coords: str) -> None:
        sel = init_sized("GhosttySelection")
        sel.start = self._term.ref(*start, coords)[0]
        sel.end = self._term.ref(*end, coords)[0]
        lib.ghostty_terminal_set(
            handle(self._term), lib.GHOSTTY_TERMINAL_OPT_SELECTION, sel
        )

    def _select_unit(self, kind: str, select: object, at: Cell) -> None:
        sel = init_sized("GhosttySelection")
        options = init_sized(f"GhosttyTerminalSelect{kind}Options")  # NULL = defaults
        options.ref = self._term.ref(*at, "viewport")[0]
        if select(handle(self._term), options, sel) == 0:  # type: ignore[operator]
            lib.ghostty_terminal_set(
                handle(self._term), lib.GHOSTTY_TERMINAL_OPT_SELECTION, sel
            )
