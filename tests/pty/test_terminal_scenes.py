"""Scene and frame naming of terminal windows."""

from __future__ import annotations

import pytest

from punt_lux.pty.listed_session import ListedSession
from punt_lux.pty.terminal_scenes import TerminalScenes


def test_a_session_gets_its_own_scene_titled_with_its_label() -> None:
    request = TerminalScenes().for_session(ListedSession("t0.7", "work", "running"))
    assert (request.scene_id, request.title) == ("terminal-t0.7", "work")


def test_the_terminal_element_names_the_session_and_no_command() -> None:
    request = TerminalScenes().for_session(ListedSession("t0.7", "work", "running"))
    (element,) = request.elements
    assert element["session"] == "t0.7"
    assert "command" not in element


def test_the_frame_is_the_scene_so_closing_the_scene_ends_the_frame() -> None:
    request = TerminalScenes().for_session(ListedSession("t0.7", "work", "running"))
    assert request.frame is None  # the frame defaults to the scene id


def test_session_of_inverts_scene_id() -> None:
    scenes = TerminalScenes()
    assert scenes.session_of(scenes.scene_id("t0.9")) == "t0.9"


@pytest.mark.parametrize("scene", ["terminal", "terminal-", "beads", "x-terminal-t0.1"])
def test_other_scenes_are_not_terminal_windows(scene: str) -> None:
    assert not TerminalScenes().owns(scene)


def test_an_empty_prefix_is_refused() -> None:
    with pytest.raises(ValueError, match="prefix is empty"):
        TerminalScenes("")


def test_session_of_refuses_a_foreign_scene() -> None:
    with pytest.raises(ValueError, match="not a terminal scene"):
        TerminalScenes().session_of("beads")
