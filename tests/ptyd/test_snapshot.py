"""Both snapshot forms restore a terminal exactly, in every state that matters.

A state is a sequence of bytes fed to a fresh terminal. The test snapshots
the result, restores it into another fresh terminal, and compares the visible
rows (untrimmed), the cursor, the active screen, the title and the modes a
program may have turned on.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty", reason="snapshot tests need the display extra")

from punt_lux.display.terminal.ffi import Terminal, terminal_title
from punt_lux.display.terminal.render_state import RenderState
from punt_lux.ptyd.snapshot import (
    SnapshotError,
    encode_binary,
    paint_vt,
    restore_binary,
    screen_rows,
    snapshot_version,
    tracked_terminal,
)

ESC = "\x1b"
CSI = ESC + "["

# DEC private modes a program may leave on, and that a viewer must learn.
MODES = (1, 7, 25, 1000, 1002, 1004, 1006, 1049, 2004)


def _long_text(lines: int) -> str:
    return "\r\n".join(f"line {i:05d} " + "x" * (i % 70) for i in range(lines))


STATES: dict[str, str] = {
    "empty": "",
    "no scroll": "aaa\r\nbbb",
    "exact fill": "L0\r\nL1\r\nL2",
    "scrolled": _long_text(50),
    "trailing newline": "L0\r\nL1\r\nL2\r\nL3\r\nL4\r\n",
    "wrapped line": "x" * 25 + "\r\nend",
    "styles": (
        CSI
        + "31mred"
        + CSI
        + "0m\r\n"
        + CSI
        + "1;44mbold on blue"
        + CSI
        + "0m\r\n"
        + CSI
        + "4;3munder italic"
        + CSI
        + "0m"
    ),
    "truecolor cells": "".join(
        CSI + f"38;2;{c * 7 % 256};{c * 3 % 256};{c % 256}m{chr(33 + c % 90)}"
        for c in range(30)
    ),
    "cursor moved": "hello\r\nworld" + CSI + "2;2H",
    "cursor hidden": "shy" + CSI + "?25l",
    "mouse tracking": "vim-like" + CSI + "?1000h" + CSI + "?1002h" + CSI + "?1006h",
    "bracketed paste and focus": "zsh" + CSI + "?2004h" + CSI + "?1004h",
    "app cursor keys": CSI + "?1h" + "less",
    "alternate screen": "primary text\r\n"
    + CSI
    + "?1049h"
    + CSI
    + "H"
    + "ALT SCREEN"
    + CSI
    + "3;5H",
    "title": ESC + "]2;my title" + ESC + "\\" + "with a title",
    "wide chars": "日本語 and emoji 🙂 end",
    "scrolling region": CSI + "2;3r" + "a\r\nb\r\nc\r\nd\r\ne",
}


def _terminal(cols: int = 10, rows: int = 3) -> Terminal:
    return tracked_terminal(cols=cols, rows=rows)


def _observe(term: Terminal) -> dict[str, object]:
    render = RenderState(term)
    try:
        render.update()
        styled_rows = render.rows
    finally:
        render.close()
    return {
        "rows": screen_rows(term),
        "styled_rows": styled_rows,
        "title": terminal_title(term),
        "cursor": term.cursor,
        "alt": bool(term.get("active_screen", "uint8_t")),
        "cursor_visible": bool(term.get("cursor_visible", "uint8_t")),
        "modes": {m: term.mode(m) for m in MODES},
    }


@pytest.mark.parametrize("name", list(STATES))
def test_binary_snapshot_round_trips(name: str) -> None:
    src = _terminal(cols=20, rows=4)
    src.feed(STATES[name])
    restored = restore_binary(encode_binary(src))
    assert _observe(restored) == _observe(src)


@pytest.mark.parametrize("name", list(STATES))
def test_vt_repaint_round_trips(name: str) -> None:
    src = _terminal(cols=20, rows=4)
    src.feed(STATES[name])
    dst = _terminal(cols=20, rows=4)
    dst.feed(paint_vt(src))
    assert _observe(dst) == _observe(src)


def test_vt_repaint_lands_the_last_row_after_a_scroll() -> None:
    """The case the naive formatter output got wrong: a screen that scrolled.

    Formatting the whole terminal emits the scrollback too, and a fresh
    viewer scrolls once more when it replays it. The recipe formats only the
    active screen, so row N stays row N.
    """
    src = _terminal(cols=10, rows=3)
    src.feed("L0\r\nL1\r\nL2\r\nL3\r\nL4\r\n")
    assert screen_rows(src) == ["L3", "L4", ""]
    dst = _terminal(cols=10, rows=3)
    dst.feed(paint_vt(src))
    assert screen_rows(dst) == ["L3", "L4", ""]
    assert dst.cursor == src.cursor == (0, 2)


def test_vt_repaint_turns_off_modes_the_viewer_had_on() -> None:
    """A viewer that missed a program's 'off' must not keep the mode."""
    src = _terminal()
    src.feed("plain")
    dst = _terminal()
    dst.feed(CSI + "?1000h" + CSI + "?2004h" + CSI + "?1049h")
    assert dst.mode(1000) and dst.mode(2004)
    dst.feed(paint_vt(src))
    assert not dst.mode(1000)
    assert not dst.mode(2004)
    assert not dst.get("active_screen", "uint8_t")


def test_vt_repaint_never_leaves_synchronized_output_on() -> None:
    src = _terminal()
    src.feed(CSI + "?2026h" + "frame in progress")
    assert src.mode(2026)
    dst = _terminal()
    dst.feed(paint_vt(src))
    assert not dst.mode(2026)
    assert screen_rows(dst)[0].startswith("frame in")


def test_binary_snapshot_carries_a_partial_escape_sequence() -> None:
    """The binary form includes the parser state; the tail then applies cleanly."""
    src = _terminal()
    src.feed("ab" + CSI + "3")  # cut inside a CSI sequence
    restored = restore_binary(encode_binary(src))
    tail = "1mred"  # completes CSI 31 m, then text
    src.feed(tail)
    restored.feed(tail)
    assert _observe(restored) == _observe(src)


def test_alternate_screen_return_preserves_primary() -> None:
    src = _terminal(cols=20, rows=4)
    src.feed(STATES["alternate screen"])
    dst = _terminal(cols=20, rows=4)
    dst.feed(paint_vt(src))
    src.feed(CSI + "?1049l")
    dst.feed(CSI + "?1049l")
    assert _observe(dst) == _observe(src)


def test_untracked_partial_sequence_is_rejected() -> None:
    src = Terminal(cols=10, rows=3)
    src.feed(CSI + "3")
    with pytest.raises(SnapshotError, match="continuation tracking"):
        encode_binary(src)


def test_continuation_tracking_is_bounded() -> None:
    src = _terminal()
    src.feed(ESC + "]2;" + "x" * 70_000)
    with pytest.raises(SnapshotError):
        encode_binary(src)
    src.feed(ESC + "\\")
    assert _observe(restore_binary(encode_binary(src))) == _observe(src)


def test_binary_snapshot_keeps_the_scrollback() -> None:
    src = _terminal(cols=20, rows=4)
    src.feed(_long_text(500))
    restored = restore_binary(encode_binary(src))
    assert restored.contents() == src.contents()


def test_restore_rejects_garbage() -> None:
    with pytest.raises(SnapshotError):
        restore_binary(b"not a snapshot")


def test_snapshot_version_names_the_pinned_binding() -> None:
    assert snapshot_version().startswith("pyghostty-")


def test_large_screen_and_history_round_trip() -> None:
    """Correctness is deterministic; performance is measured separately."""
    src = tracked_terminal(cols=200, rows=60)
    src.feed(_long_text(12_000))
    restored = restore_binary(encode_binary(src))
    assert restored.contents() == src.contents()
    dst = tracked_terminal(cols=200, rows=60)
    dst.feed(paint_vt(src))
    assert screen_rows(dst) == screen_rows(src)
