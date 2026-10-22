"""FrameDisposer — what a departure needs from the replica to take a scene out."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.identity import HubId

__all__ = ["FrameDisposer"]


class FrameDisposer(Protocol):
    """Dismiss one scene from a frame, or throw a whole frame out."""

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        """Remove a scene from ``frame``; return True if the frame is now empty."""
        ...

    def dispose_frame(self, frame_id: str, hub: HubId) -> list[str]:
        """Throw a frame and its scenes out."""
        ...
