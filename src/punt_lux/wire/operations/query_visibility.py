"""Where the display is showing a frame, as a proxied fact on a Hub read.

``list_scenes`` answers from the Hub's authoritative store, but a frame's
visibility is not the Hub's to give: the user owns where a window sits, and it is
deliberately never replicated back (DES-088). So it is fetched from the running
display when a caller asks for it, exactly as ``inspect_scene`` fetches painted
geometry --- read, never installed as Hub state.

Three states, not an optional string, because there are three genuinely
different answers. *Not requested* is the default: the caller wanted a Hub-local
read and the display was never asked, which keeps ``list_scenes`` from reaching
around on every call. *Unavailable* is a question that was asked and could not be
answered --- no display running, a faulted round trip, a frame it does not hold.
Neither of those is "the frame is on screen", and collapsing them into one
nullable field would let a caller read a failure as a fact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "FrameVisibility",
    "FrameVisibilityState",
    "VisibilityNotRequested",
    "VisibilityPresent",
    "VisibilityUnavailable",
]

type FrameVisibility = Literal["on_screen", "docked", "closed"]


class VisibilityNotRequested(BaseModel):
    """The caller asked for a Hub-local read, so the display was never asked."""

    model_config = ConfigDict(frozen=True)

    status: Literal["not_requested"] = "not_requested"


class VisibilityUnavailable(BaseModel):
    """The display was asked and could not answer for this frame."""

    model_config = ConfigDict(frozen=True)

    status: Literal["unavailable"] = "unavailable"
    reason: str


class VisibilityPresent(BaseModel):
    """The display reported where it is showing this frame."""

    model_config = ConfigDict(frozen=True)

    status: Literal["present"] = "present"
    visibility: FrameVisibility

    @property
    def is_closed(self) -> bool:
        """Whether the user has put this frame away."""
        return self.visibility == "closed"


type FrameVisibilityState = (
    VisibilityNotRequested | VisibilityUnavailable | VisibilityPresent
)
