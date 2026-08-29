"""Where the running display is showing each frame it holds.

A frame's visibility --- on screen, docked, or put away by the user --- is the
*Display's*, and it is deliberately never replicated back to the Hub (DES-088):
the user owns it, and sending it to the Hub to be re-derived from a resend is the
coupling that design exists to sever. So it is read the way every other
display-process fact is read, through :class:`DisplayControlOperations` over
luxd's one connection, and not from the Hub's own store.

That is also why it is not a field on ``list_scenes``' :class:`FrameSummary`.
Hub-authoritative reads never reach around to the display --- a rule with a test
of its own (``test_list_scenes_reads_the_hub_without_touching_the_display``) ---
and a frame's visibility is not a fact the Hub has to give.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

__all__ = ["FrameState", "FrameStates", "FrameVisibility"]

type FrameVisibility = Literal["on_screen", "docked", "closed"]


class FrameState(BaseModel):
    """One frame the display holds, and where it is showing it."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    title: str
    visibility: FrameVisibility
    scene_ids: list[str]

    @property
    def is_closed(self) -> bool:
        """Whether the user has put this frame away."""
        return self.visibility == "closed"


class FrameStates(BaseModel):
    """Every frame the display holds, whatever visibility each one is in.

    A *closed* frame is listed like any other. That is the point of the type:
    closing is a visibility and not an erasure, so a caller can no longer tell a
    frame the user shut from one that never existed by its absence here.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    frames: list[FrameState]

    @classmethod
    def from_payload(cls, payload: object) -> FrameStates | OpError:
        """Narrow the display's ``list_scenes`` reply, or refuse it.

        A reply this does not recognise is an ``OpError``, never a fabricated
        empty list: "the display answered with nothing I understand" and "the
        display holds no frames" are different facts.
        """
        if not isinstance(payload, Mapping):
            return OpError(code="rejected", reason="display reply was not a mapping")
        block = cast("Mapping[str, object]", payload)
        try:
            return cls.model_validate({"frames": block.get("frames", [])})
        except ValidationError as exc:
            return OpError.from_validation(exc)
