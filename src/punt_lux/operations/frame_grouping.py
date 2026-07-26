"""FrameAccumulator — gather the scenes sharing one frame while listing scenes.

``list_scenes`` walks the store scene by scene; each scene names the frame it
belongs to. This accumulator collects the scene ids per frame as the walk
proceeds and builds the frame's summary once every scene is gathered, keeping the
grouping bookkeeping out of the query read itself.
"""

from __future__ import annotations

from typing import Literal, Self, final

from punt_lux.operations.models.query_scenes import FrameSummary

__all__ = ["FrameAccumulator"]


@final
class FrameAccumulator:
    """Gathers the scene ids sharing one frame while ``list_scenes`` walks."""

    _title: str
    _layout: Literal["tab", "stack"]
    _scene_ids: list[str]
    __slots__ = ("_layout", "_scene_ids", "_title")

    def __new__(cls, *, title: str, layout: Literal["tab", "stack"]) -> Self:
        self = super().__new__(cls)
        self._title = title
        self._layout = layout
        self._scene_ids = []
        return self

    def add(self, scene_id: str) -> None:
        """Record a scene shown into this frame."""
        self._scene_ids.append(scene_id)

    def summary(self, frame_id: str) -> FrameSummary:
        """Build the frame's summary once every scene is gathered."""
        return FrameSummary(
            frame_id=frame_id,
            title=self._title,
            scene_count=len(self._scene_ids),
            scene_ids=self._scene_ids,
            layout=self._layout,
        )
