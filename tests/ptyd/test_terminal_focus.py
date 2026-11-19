"""Real ImGui child-window focus isolates input between terminal panes."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from imgui_bundle import ImVec2, imgui

from punt_lux.display.terminal.painter import Painter
from punt_lux.display.terminal.view import TerminalView


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
@pytest.mark.parametrize("trickle", [False, True])
def test_only_last_clicked_terminal_receives_text(
    monkeypatch: pytest.MonkeyPatch, order: tuple[int, int], trickle: bool
) -> None:
    imgui.create_context()
    io = imgui.get_io()
    io.set_ini_filename(None)
    io.display_size = ImVec2(800, 700)
    io.config_input_trickle_event_queue = trickle
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
    monkeypatch.setattr(Painter, "paint", Mock())
    views = [TerminalView(), TerminalView()]
    sent: list[list[bytes]] = [[], []]
    positions: dict[int, tuple[float, float]] = {}
    for index, view in enumerate(views):
        view.on_input = sent[index].append

    def frame() -> None:
        io.delta_time = 1 / 60
        imgui.new_frame()
        imgui.set_next_window_pos(ImVec2(0, 0))
        imgui.set_next_window_size(ImVec2(500, 600))
        imgui.begin("two terminals")
        for index in order:
            pos = imgui.get_cursor_screen_pos()
            positions[index] = (pos.x + 40, pos.y + 40)
            views[index].render_in_child(f"terminal-{index}", ImVec2(0, 220))
        imgui.end()
        imgui.render()

    try:
        frame()
        frame()
        assert sent == [[], []]
        for index in (0, 1, 0):
            io.add_mouse_pos_event(*positions[index])
            io.add_mouse_button_event(0, True)
            sent[0].clear()
            sent[1].clear()
            io.add_input_character(ord("x"))
            frame()
            frame()
            assert b"".join(sent[index]) == b"x"
            assert sent[1 - index] == []
            io.add_mouse_button_event(0, False)
            frame()
    finally:
        for view in views:
            view.close()
        imgui.destroy_context()
