"""FrameVisibility — where a frame is: painted, docked, or put away.

Visibility is the Display's, and only the user writes it. A content event —
``show()``, ``update()``, an empty push, a manifest purge — never sets a value
here; a visibility event never writes content. That separation is DES-065 R8's
whole rule, and this type is the half of it the Display owns.

``CLOSED`` is what this type adds. It used to be spelled as the absence of the
frame, which is why a frame the user shut could neither be raised (nothing left
to act on) nor kept shut (the next push recreated it). A closed frame is a frame
that is not painted; everything else about it is untouched.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["FrameVisibility"]


class FrameVisibility(Enum):
    """The three places a frame can be, and the whole of them.

    The value is the wire spelling: it rides the ``list_scenes`` payload so the
    visibility a frame is in can be observed from outside the Display.
    """

    ON_SCREEN = "on_screen"
    """Painted as an inner window."""

    DOCKED = "docked"
    """Not painted; carries a pill in the dock bar."""

    CLOSED = "closed"
    """Not painted, and carries no pill: reachable only by a named gesture."""

    @property
    def is_on_screen(self) -> bool:
        """Whether a frame in this visibility is painted."""
        return self is FrameVisibility.ON_SCREEN

    @property
    def is_docked(self) -> bool:
        """Whether a frame in this visibility shows a dock pill."""
        return self is FrameVisibility.DOCKED

    @property
    def is_closed(self) -> bool:
        """Whether the user has put a frame in this visibility away."""
        return self is FrameVisibility.CLOSED
