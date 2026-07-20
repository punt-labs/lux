"""ScenePresentation — the full presentation a scene is resent with.

The Hub is authoritative and the Display is a replica: every resend is a whole
copy of the scene, not a diff. A scene is more than its element roots — it is
also shown into a frame, with a title, a size hint, window flags, and a layout.
The Hub remembers that presentation so the background replicator can repaint the
scene from scratch after a coalesced change, a reconnect, or a display respawn,
and the frame keeps the title and geometry the caller asked for.

``ScenePresentationRegistry`` tracks one presentation per live scene, forgotten
on the same no-root-remaining criterion its sibling storage collaborators use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, Self, final, runtime_checkable

from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.element import Element as WireElement

__all__ = [
    "ScenePresentation",
    "ScenePresentationRegistry",
    "ScenePusher",
]


@runtime_checkable
class ScenePusher(Protocol):
    """The one operation the replicator needs from the display connection.

    Structural, so the presentation owns how it is sent without the domain
    layer naming the concrete ``DisplayClient``.
    """

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        title: str | None = ...,
        layout: str = ...,
        frame_id: str | None = ...,
        frame_title: str | None = ...,
        frame_size: tuple[int, int] | None = ...,
        frame_flags: dict[str, bool] | None = ...,
        frame_layout: Literal["tab", "stack"] | None = ...,
    ) -> None:
        """Send a whole scene to the display without waiting for an ack."""


@final
@dataclass(frozen=True, slots=True)
class ScenePresentation:
    """How a scene is shown: its frame, title, size hint, flags, and layout.

    Instances are never used as dict keys (``frame_flags`` is a mapping), so the
    unhashable field is immaterial — equality and immutability are what matter.
    """

    frame_id: str
    title: str | None = None
    layout: str = "single"
    frame_title: str | None = None
    frame_size: tuple[int, int] | None = None
    frame_flags: Mapping[str, bool] | None = None
    frame_layout: Literal["tab", "stack"] | None = None

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

    ``presentation_for`` and ``frame_for`` are total: an unrecorded scene falls
    back to a presentation framed by its own id — the same default the ``show``
    front door applies when no ``frame_id`` is given — so a resend of a
    never-explicitly-framed scene lands exactly where it always did.

    The map tracks scene lifetime: ``record`` when a scene is shown, ``forget``
    when it is cleared or its owning connection drops — the same unwind its
    sibling storage collaborators (index, owners, roots, children) perform.
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

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return the scene's recorded presentation, or a self-framed default."""
        return self._presentations.get(
            scene_id, ScenePresentation(frame_id=str(scene_id))
        )

    def frame_for(self, scene_id: SceneId) -> str:
        """Return the scene's recorded frame, or its own id when unrecorded."""
        return self.presentation_for(scene_id).frame_id

    def forget(self, scene_id: SceneId) -> None:
        """Drop the scene's presentation. No-op if absent.

        Called when a scene is cleared or its owning connection drops, so a
        never-re-shown scene stops occupying the map. A later re-show
        re-records; until then ``frame_for`` reverts to the scene's own id.
        """
        self._presentations.pop(scene_id, None)
