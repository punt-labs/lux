"""FrameCommands — the display-side answers to "minimize that" and "raise that".

Driven over a real ``SceneReplica`` with a real frame installed, so the handlers
are exercised against the structure the render loop reads, not a stand-in for it.
"""

from __future__ import annotations

import pytest

from punt_lux.display.frame_commands import FrameCommands
from punt_lux.display.replica import SceneReplica
from punt_lux.protocol import TextElement
from punt_lux.protocol.messages.scene import SceneMessage

_FRAME = "beads-lux"


def _manager_with_a_frame() -> SceneReplica:
    """A scene manager holding one frame, the way a pushed scene leaves it."""
    scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
    scenes.handle_framed_scene(
        SceneMessage(
            id="beads-lux",
            # A frame appears with its content: an empty push removes a scene.
            elements=[TextElement(id="t", content="Loading issues…")],
            frame_id=_FRAME,
            title="Beads",
        ),
        owner_fd=1,
    )
    scenes.consume_focus(_FRAME)  # a new frame asks for focus; start from neutral
    return scenes


def test_raising_a_frame_restores_it_and_asks_for_focus() -> None:
    """One gesture, not two: focus alone would leave the frame in the dock."""
    scenes = _manager_with_a_frame()
    scenes.minimize(_FRAME)

    answer = FrameCommands(scenes).raise_it(frame_id=_FRAME)

    assert answer == {"frame_id": _FRAME, "raised": True}
    assert scenes.frames[_FRAME].minimized is False
    assert scenes.consume_focus(_FRAME) is True


def test_raising_a_frame_that_is_not_up_is_an_answer_not_an_error() -> None:
    """The caller is finding out whether it has to push one — a fact, not a fault."""
    scenes = _manager_with_a_frame()

    answer = FrameCommands(scenes).raise_it(frame_id="no-such-frame")

    assert answer == {"frame_id": "no-such-frame", "raised": False}


def test_every_frame_command_names_a_frame() -> None:
    commands = FrameCommands(_manager_with_a_frame())
    with pytest.raises(ValueError, match="frame_id is required"):
        commands.raise_it()
    with pytest.raises(ValueError, match="frame_id is required"):
        commands.set_state()


def test_setting_state_on_a_frame_that_is_not_up_is_a_lookup_failure() -> None:
    """Unlike raising: a caller setting state on a named frame expected it to exist."""
    commands = FrameCommands(_manager_with_a_frame())
    with pytest.raises(LookupError, match="not found"):
        commands.set_state(frame_id="no-such-frame", minimized=True)


def test_setting_the_minimize_state_reports_what_changed() -> None:
    scenes = _manager_with_a_frame()
    commands = FrameCommands(scenes)

    assert commands.set_state(frame_id=_FRAME, minimized=True) == {
        "frame_id": _FRAME,
        "changed": {"minimized": True},
    }
    assert scenes.frames[_FRAME].minimized is True


def test_collapsed_is_read_as_the_minimize_state() -> None:
    """The display's older name for the same flag, still accepted on the wire."""
    scenes = _manager_with_a_frame()

    changed = FrameCommands(scenes).set_state(frame_id=_FRAME, collapsed=True)

    assert changed == {"frame_id": _FRAME, "changed": {"minimized": True}}
    assert scenes.frames[_FRAME].minimized is True
