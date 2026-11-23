"""The typed binding preserves restored handles, callbacks and single ownership."""

from __future__ import annotations

import gc
import weakref
from unittest.mock import patch

import pytest

from punt_lux.terminal.ffi import Terminal, handle, init_sized, lib
from punt_lux.terminal.ffi_snapshot import (
    SnapshotError,
    encode_binary,
    restore_binary,
    tracked_terminal,
)
from punt_lux.terminal.ffi_terminal import TerminalIO


def test_restored_terminal_owns_its_handle_and_accepts_callbacks() -> None:
    source = tracked_terminal(cols=5, rows=1)
    source.feed("hello")
    data = encode_binary(source)
    source.close()
    with patch(
        "punt_lux.terminal.ffi.weakref.finalize", wraps=weakref.finalize
    ) as register:
        restored = restore_binary(data)
        register.assert_called_once()
        assert register.call_args.args[1] == lib.ghostty_terminal_free
        assert register.call_args.args[2] == handle(restored)
        register.reset_mock()
    assert isinstance(restored, Terminal)
    assert restored.contents() == "hello"
    replies: list[bytes] = []
    io = TerminalIO(restored)
    io.on_reply(replies.append)
    io.feed(b"\x1b[6n")
    assert replies == [b"\x1b[1;5R"]
    io.close()
    io.close()
    with pytest.raises(RuntimeError, match="closed"):
        io.feed(b"x")
    reference = weakref.ref(restored)
    del restored, io
    gc.collect()
    assert reference() is None


@pytest.mark.parametrize("text", ["", "hello"])
def test_formatted_selection_handles_empty_and_populated_rows(text: str) -> None:
    term = Terminal(cols=5, rows=1)
    try:
        term.feed(text)
        selection = init_sized("GhosttySelection")
        selection.start, selection.end = term.ref(0, 0)[0], term.ref(4, 0)[0]
        assert term.formatted_selection(selection) == text
    finally:
        term.close()


@pytest.mark.parametrize("data", [b"", b"not a snapshot"])
def test_restore_rejects_invalid_input_without_registering_an_owner(
    data: bytes,
) -> None:
    with (
        patch("punt_lux.terminal.ffi.weakref.finalize") as register,
        pytest.raises(SnapshotError),
    ):
        restore_binary(data)
    register.assert_not_called()
