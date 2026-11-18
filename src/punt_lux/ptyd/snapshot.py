# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Snapshot policy, separate from the native codec and socket transport.

Binary snapshots preserve both screens, history and tracked parser state.
VT paints are a visible-state fallback, not a complete serialized emulator.
They cannot carry unfinished sequences; callers must wait for parser ground.
Native allocation and ownership live in ``terminal.ffi_snapshot``.
"""

from __future__ import annotations

from typing import Self

from punt_lux.terminal.ffi import Terminal, snapshot_version, terminal_title
from punt_lux.terminal.ffi_snapshot import (
    SnapshotError,
    active_screen_vt,
    encode_binary,
    restore_binary,
    screen_rows,
    tracked_terminal,
)

__all__ = [
    "SnapshotError",
    "VtSnapshot",
    "encode_binary",
    "paint_vt",
    "restore_binary",
    "screen_rows",
    "snapshot_version",
    "tracked_terminal",
]

_RESET = (
    b"\x18\x1b[!p"
    b"\x1b[?2026l"
    b"\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l"
    b"\x1b[?1004l\x1b[?1005l\x1b[?1006l\x1b[?1015l\x1b[?1016l"
    b"\x1b[?2004l\x1b[?1l\x1b[?66l\x1b[?2031l\x1b[?2048l"
    b"\x1b[=0;1u\x1b[?1049l\x1b[?1047l\x1b[?47l\x1b[H\x1b[2J"
)
_STRIP_FROM_SCREEN = (b"\x1b[?2026h", b"\x1b[?47h", b"\x1b[?1047h", b"\x1b[?1049h")


class VtSnapshot:
    """A visible-state repaint recipe bound to one authoritative terminal."""

    _term: Terminal

    def __new__(cls, term: Terminal) -> Self:
        self = super().__new__(cls)
        self._term = term
        return self

    @classmethod
    def paint(cls, term: Terminal) -> bytes:
        """Produce a repaint without changing the source terminal."""
        return cls(term).encode()

    def encode(self) -> bytes:
        """Repaint both grids, modes and title, without copying history."""
        return self._primary() + self._screen() + self._title()

    def _primary(self) -> bytes:
        if not self._term.get("active_screen", "uint8_t"):
            return _RESET
        primary = restore_binary(encode_binary(self._term))
        primary.feed(b"\x18\x1b[?1049l")
        return self.paint(primary) + b"\x1b[?1049h\x1b[!p"

    def _screen(self) -> bytes:
        screen = active_screen_vt(self._term)
        for seq in _STRIP_FROM_SCREEN:
            screen = screen.replace(seq, b"")
        return screen

    def _title(self) -> bytes:
        title = terminal_title(self._term)
        title = "".join(char for char in title if char >= " " and char != "\x7f")
        return b"\x1b]2;" + title.encode("utf-8", "replace") + b"\x1b\\"


paint_vt = VtSnapshot.paint
