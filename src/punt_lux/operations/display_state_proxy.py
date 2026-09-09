"""DisplayStateProxy — the Display's own widget/frame state, as a bounded read.

Structurally identical in shape to ``DisplayFactProxy``: one proxied round trip
over ``DisplayLink.query``, narrowed to a typed result or an ``OpError`` —
never installed as Hub state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_state import DisplayStateSnapshot
from punt_lux.operations.scene_listing import SceneListing

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.models.display_state import FramePresentation

__all__ = ["DisplayStateProxy"]


@final
class DisplayStateProxy:
    """Proxy the Display's own widget/frame state, narrowed to a snapshot."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def snapshot(self) -> DisplayStateSnapshot | OpError:
        """Return the display's curated widget/frame state, scene ids normalized."""
        payload = self._port.query("display_state", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        result = DisplayStateSnapshot.from_payload(payload)
        return result if isinstance(result, OpError) else self._normalized(result)

    @staticmethod
    def _normalized(snapshot: DisplayStateSnapshot) -> DisplayStateSnapshot:
        """Strip every composed scene id back to the caller's own local id.

        The display keys ``scenes``, and each frame's ``active_tab``, by
        whatever id the Hub last pushed under — the composed store key — so a
        caller can correlate this snapshot against ``inspect_scene``/
        ``list_scenes`` results it already holds, with no re-composition of
        its own.
        """
        scenes = {
            SceneListing.local_id_of(scene_id): widget
            for scene_id, widget in snapshot.scenes.items()
        }
        frames = [
            frame.model_copy(update={"active_tab": DisplayStateProxy._local_tab(frame)})
            for frame in snapshot.frames
        ]
        return DisplayStateSnapshot(scenes=scenes, frames=frames)

    @staticmethod
    def _local_tab(frame: FramePresentation) -> str | None:
        """Normalize a frame's active-tab scene id, preserving "no scenes" as None."""
        active_tab = frame.active_tab
        return None if active_tab is None else SceneListing.local_id_of(active_tab)
