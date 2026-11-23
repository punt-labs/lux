"""ScenePresentation — the full presentation a scene is resent with.

Every resend is a whole copy of the scene, not a diff. A scene is more than
its element roots — it is also shown into a frame, with a title, a size hint,
window flags, and a layout — remembered so the replicator can repaint from
scratch after a reconnect. ``ScenePresentationRegistry`` keeps one per scene,
overwritten only by a re-show.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    Self,
    cast,
    final,
    runtime_checkable,
)

from punt_lux.wire.model import SceneMessage
from punt_lux.wire.model.connection_scoped_id import ConnectionScopedId
from punt_lux.wire.model.frame_ownership import UNOWNED, FrameOwnership
from punt_lux.wire.model.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.kernel.connection_id import ConnectionId
    from punt_lux.wire.model import Element as ProtocolElement
    from punt_lux.wire.model.element import Element as WireElement

__all__ = [
    "SceneLayout",
    "ScenePresentation",
    "ScenePusher",
]


type SceneLayout = Literal["single", "rows", "columns", "grid"]


@runtime_checkable
class ScenePusher(Protocol):
    """The one operation the replicator needs from the display connection."""

    def send_scene(self, message: SceneMessage) -> None:
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

    def message(
        self,
        scene_id: SceneId | str,
        elements: Sequence[WireElement],
        ownership: FrameOwnership = UNOWNED,
    ) -> SceneMessage:
        """Build the whole-scene message that shows ``elements`` as this presents.

        ``ownership`` is resolved fresh at send time (like the menu bar), not
        part of "how a scene is shown" -- so it is a parameter here, never a
        field this frozen presentation carries or the registry persists.
        """
        return SceneMessage(
            id=str(scene_id),
            # every WireElement root is a member of the protocol Element union;
            # the cast bridges list invariance.
            elements=cast("list[ProtocolElement]", list(elements)),
            title=self.title,
            layout=self.layout,
            frame_id=self.frame_id,
            frame_title=self.frame_title,
            frame_size=self.frame_size,
            frame_flags=(
                dict(self.frame_flags) if self.frame_flags is not None else None
            ),
            frame_layout=self.frame_layout,
            frame_owner_facts=ownership.rows,
            frame_scope_label=ownership.scope_label,
        )

    def push(
        self,
        pusher: ScenePusher,
        scene_id: SceneId,
        elements: Sequence[WireElement],
        *,
        ownership: FrameOwnership,
    ) -> None:
        """Resend ``elements`` as the whole scene, with this presentation."""
        pusher.send_scene(self.message(scene_id, elements, ownership))
