"""DisplayLinkage — an observed classification of the Hub's display link.

Four states, purely derived from two facts the Hub already has: whether a
display is connected, and whether any content is live. There is no stored
transition state here, because there is nothing for the Hub to decide — the
display's process lifecycle belongs entirely to the user and the service
supervisor (docs/architecture/display-presence-demand-driven.md §7), never to
this enum or anything that computes it.
"""

from __future__ import annotations

from enum import Enum, auto

__all__ = ["DisplayLinkage"]


class DisplayLinkage(Enum):
    """How the Hub currently sees its one display connection.

    Purely observational: the Hub never causes a transition between these
    states, it only reports which one currently holds.
    """

    DISCONNECTED = auto()  # no display connected; nothing held either
    HELD = auto()  # no display connected; content is waiting
    CONNECTED_IDLE = auto()  # display connected; nothing live to show
    CONNECTED_ACTIVE = auto()  # display connected; live content is rendering

    @classmethod
    def classify(cls, *, connected: bool, live_scene_count: int) -> DisplayLinkage:
        """Classify from two observed facts — no stored transition state."""
        if not connected:
            return cls.HELD if live_scene_count > 0 else cls.DISCONNECTED
        return cls.CONNECTED_ACTIVE if live_scene_count > 0 else cls.CONNECTED_IDLE
