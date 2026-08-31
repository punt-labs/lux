"""FrameVisibilityProxy — where the running display shows and raises each frame.

Where a window sits is not the Hub's to give (DES-088) — it is fetched from
the running display when asked, the same bargain :class:`DisplayFactProxy`
strikes for painted geometry. ``of_frames`` narrows into the discriminated
states of :mod:`punt_lux.operations.models.query_visibility`; ``raise_frame``
is the one write over the same connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_write import FrameRaise
from punt_lux.operations.models.query_visibility import (
    FrameVisibilityState,
    VisibilityNotRequested,
    VisibilityPresent,
    VisibilityUnavailable,
)

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.models.inspect_scope import InspectScope

__all__ = ["FrameVisibilityProxy"]


@final
class FrameVisibilityProxy:
    """Answer where the display shows each frame, as discriminated states."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def of_frames(self, scope: InspectScope) -> dict[str, FrameVisibilityState]:
        """Return where the display shows each frame, keyed by frame id.

        Empty when the scope did not ask, so a bare ``list_scenes`` stays the
        Hub-local read it is documented to be -- one round trip, not one per
        frame, so the answer cannot change mid-list.
        """
        if not scope.want_visibility:
            return {}
        return dict(self._visibility_of(block) for block in self._frame_blocks())

    def _frame_blocks(self) -> list[Mapping[str, object]]:
        """Return the display's frame blocks, or none when it could not be asked."""
        payload = self._port.query("list_scenes", {}).resolve()
        if isinstance(payload, OpError):
            return []
        frames = payload.get("frames")
        if not isinstance(frames, list):
            return []
        return [
            cast("Mapping[str, object]", f)
            for f in cast("list[object]", frames)
            if isinstance(f, Mapping)
        ]

    @staticmethod
    def _visibility_of(
        frame: Mapping[str, object],
    ) -> tuple[str, FrameVisibilityState]:
        """Read one frame block into its id and a narrowed visibility."""
        frame_id = str(frame.get("frame_id", ""))
        reported = frame.get("visibility")
        if reported in ("on_screen", "docked", "closed"):
            return frame_id, VisibilityPresent(visibility=reported)
        return frame_id, VisibilityUnavailable(
            reason="the display reply omitted this frame's visibility"
        )

    @staticmethod
    def absent(scope: InspectScope) -> FrameVisibilityState:
        """The state for a frame the display never mentioned, under ``scope``."""
        if not scope.want_visibility:
            return VisibilityNotRequested()
        return VisibilityUnavailable(reason="the display did not report this frame")

    def raise_frame(self, frame_id: str) -> FrameRaise | OpError:
        """Bring ``frame_id`` -- already the display's own id -- to the front."""
        payload = self._port.query("raise_frame", {"frame_id": frame_id}).resolve()
        if isinstance(payload, OpError):
            return payload
        raised = FrameRaise.from_reply(payload)
        if isinstance(raised, OpError):
            return raised
        if raised.frame_id != frame_id:
            reason = f"raise_frame answered for {raised.frame_id!r}, not {frame_id!r}"
            return OpError(code="fault", reason=reason)
        return raised
