"""A frame is on screen or docked: there is no third, closed, visibility.

The user minimizes a frame to the dock bar and brings it back unchanged. Ending
a frame's content is a separate gesture a frame offers only when its owner
registered an end handler, so the visibility itself has two values.
"""

from __future__ import annotations

from typing import get_args

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.frame_placement import FramePlacement
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.wire.operations import display_frames, query_visibility


def test_a_frame_is_on_screen_or_docked_and_nothing_else() -> None:
    assert {member.value for member in FrameVisibility} == {"on_screen", "docked"}


def test_the_wire_spelling_has_the_same_two_values() -> None:
    assert get_args(display_frames.FrameVisibility.__value__) == (
        "on_screen",
        "docked",
    )
    assert get_args(query_visibility.FrameVisibility.__value__) == (
        "on_screen",
        "docked",
    )


def test_a_frame_has_no_close_gesture() -> None:
    assert not hasattr(Frame, "close")
    assert not hasattr(Frame, "is_closed")
    assert not hasattr(FramePlacement, "close")


def test_the_frame_book_keeps_no_closed_frames() -> None:
    assert not hasattr(FrameBook, "close")
    assert not hasattr(FrameBook, "closed")
