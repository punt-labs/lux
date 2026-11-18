"""The view retains its public API after terminal-state encapsulation."""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty")

from punt_lux.display.terminal.view import TerminalView


def test_view_can_feed_and_expose_its_readable_state_without_a_window() -> None:
    view = TerminalView(cols=20, rows=4)
    try:
        view.feed(b"hello")
        assert view.term.text() == "hello"
        assert (view.cols, view.rows) == (20, 4)
        assert not view.fixed_size
        assert view.render_ms == 0
        view.state.update()
        assert view.state.rows[0].runs[0].text == "hello"
    finally:
        view.close()
    view.close()  # native resources must not be freed twice


def test_input_callback_can_still_be_installed() -> None:
    view = TerminalView(cols=20, rows=4)
    sent: list[bytes] = []
    try:
        view.on_input = sent.append
        view.input.paste("hello")
        assert sent == [b"hello"]
    finally:
        view.close()
