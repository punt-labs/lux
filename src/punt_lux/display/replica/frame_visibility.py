"""FrameVisibility — where a frame is: painted, or docked.

Visibility is the Display's, and only the user writes it. A content event —
``show()``, ``update()``, an empty push, a manifest purge — never sets a value
here; a visibility event never writes content. That separation is DES-065 R8's
whole rule, and this type is the half of it the Display owns.

A frame the user minimizes keeps everything about it: its scenes, its widget
state and its tab. Ending a frame's content is a different gesture, offered only
when the frame's owner registered an end handler (DES-103 decision 6).
"""

from __future__ import annotations

from enum import Enum

__all__ = ["FrameVisibility"]


class FrameVisibility(Enum):
    """The two places a frame can be, and the whole of them.

    The value is the wire spelling: it rides the ``list_scenes`` payload so the
    visibility a frame is in can be observed from outside the Display.
    """

    ON_SCREEN = "on_screen"
    """Painted as an inner window."""

    DOCKED = "docked"
    """Not painted; carries a pill in the dock bar."""

    @property
    def is_on_screen(self) -> bool:
        """Whether a frame in this visibility is painted."""
        return self is FrameVisibility.ON_SCREEN

    @property
    def is_docked(self) -> bool:
        """Whether a frame in this visibility shows a dock pill."""
        return self is FrameVisibility.DOCKED
