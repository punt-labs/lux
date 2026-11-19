"""Program-owned pointer capture survives leaving the rendered terminal."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("pyghostty")

from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.buffer import TerminalBuffer
from punt_lux.display.terminal.input import MouseFrame
from punt_lux.display.terminal.painter import CellGrid, Painter
from punt_lux.display.terminal.view import TerminalView


@pytest.fixture
def pointer(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    io = SimpleNamespace(
        key_shift=False,
        key_ctrl=False,
        key_super=False,
        key_alt=False,
        config_mac_osx_behaviors=False,
        mouse_wheel=0,
    )
    state = SimpleNamespace(
        hovered=True,
        clicked=set(),
        released=set(),
        pos=ImVec2(25, 25),
        io=io,
    )

    def clicked(button: int) -> bool:
        return button in state.clicked

    def released(button: int) -> bool:
        return button in state.released

    monkeypatch.setattr(imgui, "get_io", lambda: io)
    monkeypatch.setattr(imgui, "get_mouse_pos", lambda: state.pos)
    monkeypatch.setattr(imgui, "is_mouse_clicked", clicked)
    monkeypatch.setattr(imgui, "is_mouse_released", released)
    monkeypatch.setattr(imgui, "is_window_hovered", lambda: state.hovered)
    monkeypatch.setattr(imgui, "is_window_focused", lambda: False)
    monkeypatch.setattr(imgui, "get_cursor_screen_pos", lambda: ImVec2(0, 0))
    monkeypatch.setattr(imgui, "get_content_region_avail", lambda: ImVec2(200, 40))
    monkeypatch.setattr(imgui, "dummy", Mock())
    monkeypatch.setattr(Painter, "paint", Mock())
    monkeypatch.setattr(
        CellGrid, "for_current_font", Mock(return_value=CellGrid(ImVec2(0, 0), 10, 10))
    )
    return state


@pytest.fixture
def terminal() -> Iterator[tuple[TerminalView, TerminalBuffer, list[bytes]]]:
    sent: list[bytes] = []
    view = TerminalView(20, 4)
    view._on_input = sent.append
    buffer = view._buffer
    view.feed(b"\x1b[?1002h\x1b[?1006h")
    try:
        yield view, buffer, sent
    finally:
        view.close()


@pytest.mark.parametrize("shift", [False, True])
def test_release_outside_hover_reaches_program(
    pointer: SimpleNamespace,
    terminal: tuple[TerminalView, TerminalBuffer, list[bytes]],
    shift: bool,
) -> None:
    view, buffer, sent = terminal
    pointer.clicked = {imgui.MouseButton_.left}
    view.render()
    assert bool(buffer.input.mouse_captured)
    assert sent[0] == b"\x1b[<0;3;3M"
    sent.clear()
    pointer.clicked = set()
    pointer.released = {imgui.MouseButton_.left}
    pointer.hovered = False
    pointer.io.key_shift = shift
    pointer.io.mouse_wheel = 3
    pointer.clicked = {imgui.MouseButton_.right}
    pointer.pos = ImVec2(-50, 600)
    view.render()
    assert not bool(buffer.input.mouse_captured)
    assert sent == [b"\x1b[<4;1;4m" if shift else b"\x1b[<0;1;4m"]
    sent.clear()
    pointer.released = set()
    with patch.object(buffer.input, "poll_mouse") as poll:
        view.render()
    poll.assert_not_called()
    assert sent == []


def test_capture_retained_until_all_program_buttons_release(
    pointer: SimpleNamespace,
    terminal: tuple[TerminalView, TerminalBuffer, list[bytes]],
) -> None:
    view, buffer, sent = terminal
    pointer.clicked = {imgui.MouseButton_.left, imgui.MouseButton_.right}
    view.render()
    pointer.hovered = False
    pointer.clicked = set()
    pointer.released = {imgui.MouseButton_.left}
    view.render()
    assert bool(buffer.input.mouse_captured)
    pointer.released = {imgui.MouseButton_.right}
    view.render()
    assert not bool(buffer.input.mouse_captured)
    assert sent[-1].endswith(b"m")


def test_unowned_click_outside_hover_does_not_capture(
    pointer: SimpleNamespace,
    terminal: tuple[TerminalView, TerminalBuffer, list[bytes]],
) -> None:
    view, buffer, sent = terminal
    pointer.hovered = False
    pointer.clicked = {imgui.MouseButton_.left}
    view.render()
    assert not bool(buffer.input.mouse_captured)
    assert sent == []


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (ImVec2(-10, -20), (0, 0)),
        (ImVec2(500, 500), (199, 39)),
        (ImVec2(25, 25), (25, 25)),
    ],
)
def test_program_coordinates_clamp_to_grid(
    pointer: SimpleNamespace, position: ImVec2, expected: tuple[int, int]
) -> None:
    pointer.pos = position
    frame = MouseFrame.at_pointer(ImVec2(0, 0), (10, 10), (20, 4))
    assert (frame.x, frame.y) == expected
