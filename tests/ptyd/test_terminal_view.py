"""The view retains its public API after terminal-state encapsulation."""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty")

from punt_lux.display.terminal.view import TerminalView
from punt_lux.protocol.pty.attach import AttachRequest


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


@pytest.mark.parametrize(
    ("requested", "expected"),
    [((100, 30), (100, 30)), ((0, -1), (10, 3)), ((2000, 1000), (1024, 512))],
)
def test_fit_clamps_to_wire_limits(
    requested: tuple[int, int], expected: tuple[int, int]
) -> None:
    view = TerminalView(cols=20, rows=4)
    sent: list[tuple[int, int]] = []

    def resized(cols: int, rows: int) -> None:
        sent.append((cols, rows))

    view.on_resize = resized
    try:
        view._fit(*requested)
        assert sent == [expected]
        AttachRequest(1, "terminal", cols=expected[0], rows=expected[1])
        assert (view.cols, view.rows) == expected
        view._fit(*requested)
        assert sent == [expected]
    finally:
        view.close()
