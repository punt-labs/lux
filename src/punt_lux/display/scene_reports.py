"""SceneReports -- what the display reports about the scenes and frames it holds."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from punt_lux.display.replica import SceneReplica

__all__ = ["SceneReports"]


@final
class SceneReports:
    """Answer ``list_scenes`` and ``display_state`` from the scene replica."""

    _scenes: SceneReplica
    __slots__ = ("_scenes",)

    def __new__(cls, scenes: SceneReplica) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        return self

    def list_scenes(self, **_kwargs: Any) -> dict[str, Any]:
        """Every scene with its frame and owner, and every frame with its scenes."""
        sm = self._scenes
        scenes: list[dict[str, Any]] = []
        for fid, frame in sm.frames.items():
            for sid, scene in frame.scenes.items():
                scenes.append(
                    {
                        "scene_id": sid,
                        "element_count": len(scene.elements),
                        "frame_id": fid,
                        "owner_fd": sm.scene_to_owner.get(sid),
                    }
                )
        frames: list[dict[str, Any]] = []
        for fid, frame in sm.frames.items():
            frame_scenes = [s for s, f in sm.scene_to_frame.items() if f == fid]
            frames.append(
                {
                    "frame_id": fid,
                    "title": frame.heading.title,
                    "scope_label": frame.heading.scope_label,  # None: no owner named
                    "scene_count": len(frame_scenes),
                    "scene_ids": frame_scenes,
                    "layout": frame.hints.layout,
                    # Where the user left it. Display-local and never replicated
                    # back, but reported, because it is the only way an observer
                    # outside this process can tell a closed frame from an
                    # absent one.
                    "visibility": frame.visibility.value,
                }
            )
        return {"scenes": scenes, "frames": frames}

    def display_state(self, **_kwargs: Any) -> dict[str, Any]:
        """Curated widget and frame facts, unkeyed."""
        sm = self._scenes
        return {"scenes": sm.all_widget_snapshots(), "frames": sm.frame_presentations()}
