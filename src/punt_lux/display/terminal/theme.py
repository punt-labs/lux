# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
"""Default terminal palette, independent of input and frame layout."""

from __future__ import annotations

from typing import ClassVar

from punt_lux.display.terminal.cell_style import RGB
from punt_lux.terminal.ffi import Terminal, ffi, handle, lib


class TerminalTheme:
    """Default colours and the operation that installs them into Ghostty."""

    # imgui_terminal's default theme, so the two widgets can be compared directly.
    FG: ClassVar[RGB] = (0xCC, 0xCC, 0xCC)
    BG: ClassVar[RGB] = (0x1E, 0x1E, 0x1E)
    ANSI16: ClassVar[tuple[RGB, ...]] = (
        (0x00, 0x00, 0x00), (0xC2, 0x36, 0x21), (0x25, 0xBC, 0x24), (0xAD, 0xAD, 0x27),
        (0x49, 0x2E, 0xE1), (0xD3, 0x38, 0xD3), (0x33, 0xBB, 0xC8), (0xCB, 0xCC, 0xCD),
        (0x81, 0x83, 0x83), (0xFC, 0x39, 0x1F), (0x31, 0xE7, 0x22), (0xEA, 0xEC, 0x23),
        (0x58, 0x33, 0xFF), (0xF9, 0x35, 0xF8), (0x14, 0xF0, 0xF0), (0xE9, 0xEB, 0xEB),
    )  # fmt: skip

    @classmethod
    def apply(cls, term: Terminal) -> None:
        """Override palette entries 0-15; keep Ghostty's 16-255 (xterm cube, greys)."""
        palette = ffi.new("GhosttyColorRgb[256]")
        lib.ghostty_terminal_get(
            handle(term), lib.GHOSTTY_TERMINAL_DATA_COLOR_PALETTE, palette
        )
        for i, (r, g, b) in enumerate(cls.ANSI16):
            palette[i].r, palette[i].g, palette[i].b = r, g, b
        lib.ghostty_terminal_set(
            handle(term), lib.GHOSTTY_TERMINAL_OPT_COLOR_PALETTE, palette
        )
