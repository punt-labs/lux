"""Hub-owned registry of scene presentation values."""

from __future__ import annotations

from operator import attrgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.wire.model import scene_presentation
from punt_lux.wire.model.connection_scoped_id import ConnectionScopedId

if TYPE_CHECKING:
    from punt_lux.kernel.connection_id import ConnectionId
    from punt_lux.wire.model.ids import SceneId

__all__ = ["ScenePresentationRegistry"]


@final
class ScenePresentationRegistry:
    """``SceneId → ScenePresentation`` — where and how each scene was shown.

    ``presentation_for`` is total: an unrecorded scene falls back to a
    presentation framed by its own id, so a resend of a never-explicitly-framed
    scene lands where it always did. Kept until blanked away or re-shown.
    """

    _presentations: dict[SceneId, scene_presentation.ScenePresentation]
    __slots__ = ("_presentations",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._presentations = {}
        return self

    def record(
        self, scene_id: SceneId, presentation: scene_presentation.ScenePresentation
    ) -> None:
        """Remember how a scene was shown, for a later whole-scene resend.

        Dict order is each frame's entry order, the rule the Display's
        ``Frame.scene_order`` follows too: a scene moved into a frame joins its
        end, a re-show in place keeps its seat. Overwriting a key keeps its slot,
        so a move drops the old entry first.
        """
        held = self._presentations.get(scene_id, presentation)
        if held.frame_id != presentation.frame_id:
            del self._presentations[scene_id]
        self._presentations[scene_id] = presentation

    def forget(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation; a no-op if it was never recorded."""
        self._presentations.pop(scene_id, None)

    def presentation_for(
        self, scene_id: SceneId
    ) -> scene_presentation.ScenePresentation:
        """Return the scene's recorded presentation, or a self-framed default."""
        default = scene_presentation.ScenePresentation(frame_id=str(scene_id))
        return self._presentations.get(scene_id, default)

    def scenes_in_frame(self, frame_id: str) -> list[SceneId]:
        """Return every recorded scene shown in ``frame_id``, oldest entrant first."""
        here = filter(lambda e: e[1].frame_id == frame_id, self._presentations.items())
        return [scene_id for scene_id, _ in here]

    def frame_id_for_local(
        self, local_id: str, *, connection: ConnectionId
    ) -> str | None:
        """Return ``connection``'s own frame id named ``local_id``, or None."""
        scoped_id = ConnectionScopedId.compose(connection, local_id)
        frame_ids = map(attrgetter("frame_id"), self._presentations.values())
        return scoped_id if scoped_id in frame_ids else None
