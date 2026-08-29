"""FrameVisibilityProxy — where the running display is showing each frame.

The Hub answers ``list_scenes`` from its authoritative store, but one field on
each frame is not the Hub's to give: where the window sits. The user owns it and
it is deliberately never replicated back (DES-088), so it is fetched from the
running display when the caller asks --- the same bargain
:class:`DisplayFactProxy` strikes for painted geometry, and a sibling of it
rather than a second job inside it.

Everything here narrows into the discriminated states of
:mod:`punt_lux.operations.models.query_visibility`, so a caller can always tell
"nobody asked" from "the display could not answer" from an actual answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.operations.models.common import OpError
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

        Empty when the scope did not ask, so a bare ``list_scenes`` never reaches
        around to the display and stays the Hub-local read it is documented to
        be. One round trip for the whole call rather than one per frame: asking
        repeatedly would let the answer change mid-list.
        """
        if not scope.want_visibility:
            return {}
        return dict(self._visibility_of(block) for block in self._frame_blocks())

    def _frame_blocks(self) -> list[Mapping[str, object]]:
        """Return the display's frame blocks, or none when it could not be asked.

        A down display, a faulted round trip, and a reply whose ``frames`` is not
        a list all come back the same way here — as nothing to read. The caller
        turns that into one unavailable-with-a-reason per frame rather than
        letting an empty mapping read as "no frames".
        """
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
        """The state for a frame the display never mentioned, under ``scope``.

        Not-requested when the caller did not ask; otherwise the question was put
        and went unanswered, which is a different fact and says so.
        """
        if not scope.want_visibility:
            return VisibilityNotRequested()
        return VisibilityUnavailable(reason="the display did not report this frame")
