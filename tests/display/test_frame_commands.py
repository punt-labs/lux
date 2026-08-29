"""FrameCommands — the display-side answers to "collapse that" and "raise that".

Driven over a real ``SceneReplica`` with a real frame installed, so the handlers
are exercised against the structure the render loop reads, not a stand-in for it.

The raise tests are where DES-065 R8's load-bearing guarantee is pinned down:
one gesture restores a frame from *every* visibility, closed included. That is
what makes closing a decision the user can take back, and it is what an applet's
menu-entry click (DES-063's raise-first pattern) depends on.
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
    return scenes


def test_a_pushed_scene_leaves_no_focus_request_behind() -> None:
    """The premise every raise test below rests on: a push is not a raise."""
    assert _manager_with_a_frame().consume_focus(_FRAME) is False


def test_raising_a_docked_frame_restores_it_and_asks_for_focus() -> None:
    """One gesture, not two: focus alone would leave the frame in the dock."""
    scenes = _manager_with_a_frame()
    scenes.minimize(_FRAME)

    answer = FrameCommands(scenes).raise_it(frame_id=_FRAME)

    assert answer == {"frame_id": _FRAME, "raised": True}
    assert scenes.frames[_FRAME].is_on_screen is True
    assert scenes.consume_focus(_FRAME) is True


def test_raising_a_closed_frame_restores_it_and_asks_for_focus() -> None:
    """Bug A's partition (A3), and the whole reason closed is a visibility state.

    Closing used to pop the frame out of the book, so the one gesture that
    restores a frame had nothing left to act on and answered ``raised: false``.
    """
    scenes = _manager_with_a_frame()
    scenes.close(_FRAME)

    answer = FrameCommands(scenes).raise_it(frame_id=_FRAME)

    assert answer == {"frame_id": _FRAME, "raised": True}
    assert scenes.frames[_FRAME].is_on_screen is True
    assert scenes.consume_focus(_FRAME) is True


def test_raising_an_on_screen_frame_asks_for_focus() -> None:
    """A frame behind others is raised by putting it in front, and nothing else."""
    scenes = _manager_with_a_frame()

    answer = FrameCommands(scenes).raise_it(frame_id=_FRAME)

    assert answer == {"frame_id": _FRAME, "raised": True}
    assert scenes.frames[_FRAME].is_on_screen is True
    assert scenes.consume_focus(_FRAME) is True


def test_close_then_raise_puts_the_frame_back_on_screen_with_its_content() -> None:
    """F1's composite (A5) — the test that fails if either half of the fix ships alone.

    Retiring the ``is_new`` side effect without keeping the closed frame makes
    the close button a one-way door, because that side effect *was* the only
    reopen path. Keeping the frame without retiring the side effect leaves the
    frame reopening itself on the next background push. Only both together give
    this: the user shuts a window, asks for it back by name, and gets back the
    window they shut.
    """
    scenes = _manager_with_a_frame()
    commands = FrameCommands(scenes)

    scenes.close(_FRAME)
    assert scenes.frames[_FRAME].is_closed is True

    assert commands.raise_it(frame_id=_FRAME) == {"frame_id": _FRAME, "raised": True}
    assert scenes.frames[_FRAME].is_on_screen is True
    assert scenes.resolve_scene("beads-lux") is not None


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
    assert scenes.frames[_FRAME].is_docked is True


def test_clearing_the_minimize_state_brings_the_frame_back_on_screen() -> None:
    scenes = _manager_with_a_frame()
    scenes.minimize(_FRAME)

    changed = FrameCommands(scenes).set_state(frame_id=_FRAME, minimized=False)

    assert changed == {"frame_id": _FRAME, "changed": {"minimized": False}}
    assert scenes.frames[_FRAME].is_on_screen is True


def test_setting_state_carries_no_focus_of_its_own() -> None:
    """Only a raise takes focus. ``set_state`` moves a frame without announcing it."""
    scenes = _manager_with_a_frame()
    scenes.minimize(_FRAME)

    FrameCommands(scenes).set_state(frame_id=_FRAME, minimized=False)

    assert scenes.consume_focus(_FRAME) is False


def test_collapsed_is_read_as_the_minimize_state() -> None:
    """The display's older name for the same state, still accepted on the wire."""
    scenes = _manager_with_a_frame()

    changed = FrameCommands(scenes).set_state(frame_id=_FRAME, collapsed=True)

    assert changed == {"frame_id": _FRAME, "changed": {"minimized": True}}
    assert scenes.frames[_FRAME].is_docked is True
