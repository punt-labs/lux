"""Snapshot policy, separate from the native codec and socket transport.

Binary snapshots preserve both screens, history and tracked parser state, but
cannot be cut once continuation tracking is exhausted. VT paints repaint only
the visible screen and title, so they can be cut in any parser state.
Native allocation and ownership live in ``terminal.ffi_snapshot``.
"""

from __future__ import annotations

import re
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
_ENTER_ALTERNATE = b"\x1b[?1049h\x1b[!p"
_STRIP_FROM_SCREEN = re.compile(
    b"|".join(
        re.escape(seq)
        for seq in (b"\x1b[?2026h", b"\x1b[?47h", b"\x1b[?1047h", b"\x1b[?1049h")
    )
)
_TITLE_CONTROLS = re.compile("[\x00-\x1f\x7f]")


class VtSnapshot:
    """A visible-state repaint recipe bound to one authoritative terminal."""

    _term: Terminal

    def __new__(cls, term: Terminal) -> Self:
        self = super().__new__(cls)
        self._term = term
        return self

    def encode_visible(self) -> bytes:
        """Repaint the active screen and title without the binary codec.

        The hidden primary grid is not carried, so this works when continuation
        tracking is exhausted and ``encode_binary`` would raise.
        """
        entry = b""
        if self._term.get("active_screen", "uint8_t"):
            entry = _ENTER_ALTERNATE
        return _RESET + entry + self._screen() + self._title()

    def _screen(self) -> bytes:
        return _STRIP_FROM_SCREEN.sub(b"", active_screen_vt(self._term))

    def _title(self) -> bytes:
        title = _TITLE_CONTROLS.sub("", terminal_title(self._term))
        return b"\x1b]2;" + title.encode("utf-8", "replace") + b"\x1b\\"
