"""Define the operation port used by frame removal commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import Ok, OpError, Scope

__all__ = ["FrameOps"]


@runtime_checkable
class FrameOps(Protocol):
    """The ops surface the frame commands read."""

    def remove_frame(self, frame_id: str, *, scope: Scope) -> Ok | OpError:
        """Remove the caller's own frame's content: tear down its scenes on the Hub."""
        ...
