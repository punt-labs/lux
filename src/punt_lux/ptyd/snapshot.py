# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Snapshot policy, separate from the native codec and from socket transport.

Binary snapshots preserve both screens, history and tracked parser state.
VT paints are a visible-state fallback, not a complete serialized emulator.
They cannot carry an unfinished sequence and must be taken at parser ground.

Formatting the whole terminal emits history and drops the final empty row.
Selecting the active grid instead fixes the row shift discovered in research.
Native calls and ownership live in ``display.terminal.ffi_snapshot``.
"""

from __future__ import annotations

from punt_lux.display.terminal.ffi import Terminal, snapshot_version, terminal_title
from punt_lux.display.terminal.ffi_snapshot import (
    SnapshotError,
    active_screen_vt,
    encode_binary,
    restore_binary,
    screen_rows,
    tracked_terminal,
)

__all__ = [
    "SnapshotError",
    "encode_binary",
    "paint_vt",
    "restore_binary",
    "screen_rows",
    "snapshot_version",
    "tracked_terminal",
]

_RESET = (
    b"\x18\x1b[!p"  # cancel unfinished input; soft reset
    b"\x1b[?2026l"
    b"\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l"
    b"\x1b[?1004l\x1b[?1005l\x1b[?1006l\x1b[?1015l\x1b[?1016l"
    b"\x1b[?2004l\x1b[?1l\x1b[?66l\x1b[?2031l\x1b[?2048l"
    b"\x1b[=0;1u\x1b[?1049l\x1b[?1047l\x1b[?47l\x1b[H\x1b[2J"
)
_STRIP_FROM_SCREEN = (b"\x1b[?2026h", b"\x1b[?47h", b"\x1b[?1047h", b"\x1b[?1049h")


def paint_vt(term: Terminal) -> bytes:
    """Repaint both visible grids, modes and title, without copying history.

    When the alternate screen is active, paint the hidden primary from a
    binary clone first. Never mutate the live terminal to access its primary.
    The formatter cannot carry parser continuation or all hidden emulator
    state; binary snapshots are the daemon's normal attach format.
    """
    out = bytearray(_RESET)
    if term.get("active_screen", "uint8_t"):
        primary = restore_binary(encode_binary(term))
        primary.feed(b"\x18\x1b[?1049l")
        out = bytearray(paint_vt(primary))
        out += b"\x1b[?1049h\x1b[!p"
    screen = active_screen_vt(term)
    for seq in _STRIP_FROM_SCREEN:
        screen = screen.replace(seq, b"")
    out += screen
    title = terminal_title(term)
    # Titles are terminal input too: do not replay embedded control sequences.
    title = "".join(char for char in title if char >= " " and char != "\x7f")
    out += b"\x1b]2;" + title.encode("utf-8", "replace") + b"\x1b\\"
    return bytes(out)
