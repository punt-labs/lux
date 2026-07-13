"""FrameRegistry — ``SceneId → frame_id`` mapping for Hub-side re-push.

A scene is shown into a frame. The frame defaults to the scene's own id, but an
agent may place a scene in a differently-named frame (multi-scene tab layouts).
The Hub remembers that association so a re-push — the whole-UI resend a D21
interaction or an ``update`` / ``clear`` triggers — sends the scene back into
its original frame instead of a frame named for the scene.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.ids import SceneId

__all__ = ["FrameRegistry"]


class FrameRegistry:
    """``SceneId → frame_id`` mapping remembering where each scene was shown.

    A thin typed wrapper around the frame dict. ``frame_for`` is total: an
    unrecorded scene falls back to its own id as the frame name — the same
    default the ``show`` front door applies when no ``frame_id`` is given — so a
    re-push of a never-explicitly-framed scene lands exactly where it always did.
    """

    _frames: dict[SceneId, str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = {}
        return self

    def record(self, scene_id: SceneId, frame_id: str) -> None:
        """Remember the frame a scene was shown in."""
        self._frames[scene_id] = frame_id

    def frame_for(self, scene_id: SceneId) -> str:
        """Return the scene's recorded frame, or its own id when unrecorded.

        Total by design (PY-EH-8): the default frame is named for the scene, so
        an unrecorded scene resolves to ``scene_id`` rather than raising —
        precisely the frame the ``show`` default would have produced.
        """
        return self._frames.get(scene_id, scene_id)
