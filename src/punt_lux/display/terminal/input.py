# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""ImGui keyboard, mouse and paste → bytes for the program (ADR-0004).

The widget never builds escape sequences itself. Ghostty's encoders decide
the bytes from the terminal's current modes: cursor-key and keypad modes, the
kitty keyboard protocol, mouse tracking mode and format (X10/SGR/…) and
bracketed paste. This module only translates ImGui events into Ghostty event
objects. The only exception is wheel-to-arrows, an xterm convention for
programs that use the alternate screen without the mouse (``less``, ``man``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.input_events import (
    KeyboardEvents,
    KeyEncoding,
    MouseEvents,
)
from punt_lux.terminal.ffi import Terminal, ffi, lib

__all__ = ["Input", "MouseFrame"]


@dataclass(frozen=True, slots=True)
class MouseFrame:
    """The pointer, relative to the grid origin, and the grid's geometry."""

    x: float
    y: float
    cell_w: float
    cell_h: float
    cols: int
    rows: int
    hovered: bool = True

    @classmethod
    def at_pointer(
        cls,
        origin: ImVec2,
        cell: tuple[float, float],
        size: tuple[int, int],
    ) -> Self:
        mouse = imgui.get_mouse_pos()
        cols, rows = size
        cell_w, cell_h = cell
        return cls(
            min(max(0, mouse.x - origin.x), cols * cell_w - 1),
            min(max(0, mouse.y - origin.y), rows * cell_h - 1),
            cell_w,
            cell_h,
            cols,
            rows,
            imgui.is_window_hovered(),
        )


class Input:
    """Owns one terminal's key and mouse encoders; sends bytes via ``write``."""

    _term: Terminal
    _write: Callable[[bytes], None]
    _keys: KeyEncoding
    _mouse: MouseEvents
    _out: Any
    _out_len: Any

    def __new__(cls, term: Terminal, write: Callable[[bytes], None]) -> Self:
        self = super().__new__(cls)
        self._term = term
        self._write = write
        self._keys = KeyEncoding()
        self._mouse = MouseEvents()
        self._out = ffi.new("char[]", 256)
        self._out_len = ffi.new("size_t*")
        return self

    def close(self) -> None:
        self._keys.close()
        self._mouse.close()

    @property
    def mouse_captured(self) -> bool:
        return self._mouse.captured

    # -- keyboard ----------------------------------------------------------
    def poll_keyboard(self) -> bool:
        """Send presses, repeats, releases and committed text from this frame."""
        return KeyboardEvents.poll(self.key)

    def key(self, key: int, mods: int, text: str | None, action: int) -> bool:
        """Encode and send one key event. True if it produced bytes."""
        return self._emit(
            self._keys.encode(
                self._term, (key, mods, text, action), self._out, self._out_len
            )
        )

    # -- paste -------------------------------------------------------------
    def paste(self, text: str) -> None:
        """Send pasted text: bracketed when the program asked (mode 2004).

        Ghostty also neutralises control characters (an embedded
        ``ESC[201~`` cannot end the paste early) and maps newlines to CR
        when not bracketed.
        """
        if not text:
            return
        data = text.encode()
        src = ffi.new("char[]", data)  # rewritten in place by the encoder
        out = ffi.new("char[]", len(data) + 16)  # room for the two brackets
        n = ffi.new("size_t*")
        bracketed = self._term.mode(2004)
        if lib.ghostty_paste_encode(src, len(data), bracketed, out, len(out), n) == 0:
            self._write(ffi.buffer(out, n[0])[:])

    # -- mouse -------------------------------------------------------------
    def program_wants_mouse(self, *, hovered: bool = True) -> bool:
        """Retain captured buttons; new gestures require tracking and hover."""
        tracking = bool(self._term.get("mouse_tracking", "bool"))
        return self._mouse.captured or (
            hovered and tracking and not imgui.get_io().key_shift
        )

    def poll_mouse(self, frame: MouseFrame) -> None:
        """Forward this frame's buttons, motion and wheel to the program."""
        self._mouse.poll(frame, self._term, self._out, self._out_len, self._emit)

    def _emit(self, result: int) -> bool:
        """Send the encoder's output, if any. True if bytes were sent."""
        if result != 0 or not self._out_len[0]:
            return False
        self._write(ffi.buffer(self._out, self._out_len[0])[:])
        return True
