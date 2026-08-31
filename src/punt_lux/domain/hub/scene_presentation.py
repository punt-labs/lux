"""ScenePresentation — the full presentation a scene is resent with.

Every resend is a whole copy of the scene, not a diff. A scene is more than
its element roots — it is also shown into a frame, with a title, a size hint,
window flags, and a layout — remembered so the replicator can repaint from
scratch after a reconnect. ``ScenePresentationRegistry`` keeps one per scene,
overwritten only by a re-show.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from operator import attrgetter
from typing import TYPE_CHECKING, Literal, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.ids import ConnectionId

__all__ = [
    "SceneLayout",
    "ScenePresentation",
    "ScenePresentationRegistry",
    "ScenePusher",
]

type SceneLayout = Literal["single", "rows", "columns", "grid"]


@runtime_checkable
class ScenePusher(Protocol):
    """The one operation the replicator needs from the display connection.

    Structural, so the presentation owns how it is sent without naming the
    concrete ``DisplayLink``.
    """

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        title: str | None = ...,
        layout: SceneLayout = ...,
        frame_id: str,
        frame_title: str | None = ...,
        frame_size: tuple[int, int] | None = ...,
        frame_flags: dict[str, bool] | None = ...,
        frame_layout: Literal["tab", "stack"] | None = ...,
    ) -> None:
        """Send a whole scene to the display without waiting for an ack."""


@final
@dataclass(frozen=True, slots=True)
class ScenePresentation:
    """How a scene is shown: its frame, title, size hint, flags, and layout."""

    frame_id: str
    title: str | None = None
    layout: SceneLayout = "single"
    frame_title: str | None = None
    frame_size: tuple[int, int] | None = None
    frame_flags: Mapping[str, bool] | None = None
    frame_layout: Literal["tab", "stack"] | None = None

    def scoped(self, owner: ConnectionId) -> Self:
        """Return this presentation with its frame id namespaced to `owner`."""
        return replace(self, frame_id=ConnectionScopedId.compose(owner, self.frame_id))

    def push(
        self,
        pusher: ScenePusher,
        scene_id: SceneId,
        elements: Sequence[WireElement],
    ) -> None:
        """Resend ``elements`` as the whole scene, with this presentation."""
        pusher.show_async(
            str(scene_id),
            elements=list(elements),
            title=self.title,
            layout=self.layout,
            frame_id=self.frame_id,
            frame_title=self.frame_title,
            frame_size=self.frame_size,
            frame_flags=(
                dict(self.frame_flags) if self.frame_flags is not None else None
            ),
            frame_layout=self.frame_layout,
        )


@final
class ScenePresentationRegistry:
    """``SceneId → ScenePresentation`` — where and how each scene was shown.

    ``presentation_for`` is total: an unrecorded scene falls back to a
    presentation framed by its own id, so a resend of a never-explicitly-framed
    scene lands where it always did. Kept until blanked away or re-shown.
    """

    _presentations: dict[SceneId, ScenePresentation]
    __slots__ = ("_presentations",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._presentations = {}
        return self

    def record(self, scene_id: SceneId, presentation: ScenePresentation) -> None:
        """Remember how a scene was shown, for a later whole-scene resend."""
        self._presentations[scene_id] = presentation

    def forget(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation; a no-op if it was never recorded."""
        self._presentations.pop(scene_id, None)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return the scene's recorded presentation, or a self-framed default."""
        default = ScenePresentation(frame_id=str(scene_id))
        return self._presentations.get(scene_id, default)

    def scenes_in_frame(self, frame_id: str) -> list[SceneId]:
        """Return every recorded scene shown in ``frame_id`` -- for closing it."""
        return [s for s, p in self._presentations.items() if p.frame_id == frame_id]

    def frame_id_for_local(self, local_id: str) -> str | None:
        """Return the connection-scoped frame id named ``local_id``, or None.

        A caller names a frame by its local id, not the connection that
        scoped it (DES-086). None both for an unknown name and one two
        connections share.
        """
        ids = map(attrgetter("frame_id"), self._presentations.values())
        matches = set(filter(lambda i: self._local_id(i) == local_id, ids))
        return next(iter(matches)) if len(matches) == 1 else None

    @staticmethod
    def _local_id(frame_id: str) -> str:
        """Return ``frame_id``'s local part, or itself if it carries none."""
        local = frame_id
        with suppress(ValueError):
            local = ConnectionScopedId.from_composed(frame_id).local_id
        return local
