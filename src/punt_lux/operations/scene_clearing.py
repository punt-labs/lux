"""SceneClearer — blank the scenes one connection owns, and say when it could not.

The teardown half of the scene operations, kept apart from the install half
because it answers a different question: not "is this tree fit to install?" but
"which of these roots are yours to remove?". The writer enforces that, removing
only the caller's roots and leaving every other owner's standing.

A scene-scoped clear that removes nothing must not report ``cleared``. Two very
different things look alike from the caller's side — a scene that does not exist,
and one that exists but holds nothing of theirs — so each gets its own answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.ids import SceneId
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import Cleared

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker

__all__ = ["SceneClearer"]


@final
class SceneClearer:
    """Remove a connection's own roots and mark every emptied scene for resend."""

    _display: HubDisplay
    _replicator: DirtyMarker
    __slots__ = ("_display", "_replicator")

    def __new__(cls, display: HubDisplay, replicator: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        return self

    def clear(
        self, owner: ConnectionId, scene_id: str | None = None
    ) -> Cleared | OpError:
        """Blank ``owner``'s scenes — all of them, or just the one named.

        ``scene_id`` absent is the whole-owner clear, which removing nothing
        leaves a settled no-op; naming a scene makes an empty removal an answer
        the caller needs, so it is reported rather than passed off as success.
        A named ``scene_id`` is composed against ``owner`` before it reaches
        the store, the same choke point ``install``/``update`` compose at, so
        a caller can only ever clear a scene it is the connection for
        (DES-086).
        """
        try:
            target = (
                SceneId(ConnectionScopedId.compose(owner, scene_id))
                if scene_id is not None
                else None
            )
        except ValueError as exc:
            return OpError(code="invalid_request", reason=str(exc))
        touched = HubSceneWriter(self._display).clear(owner, target)
        if target is not None and scene_id is not None and not touched:
            return self._scoped_miss(target, scene_id)
        for emptied in touched:
            self._replicator.mark_dirty(emptied)
        return Cleared()

    def _scoped_miss(self, composed: SceneId, local_id: str) -> OpError:
        """Say why a scene-scoped clear removed nothing: unknown scene, or unowned.

        No non-removed root means the scene is unknown (the ``not_found``
        ``inspect_scene`` returns); roots present but none the caller owns is an
        ownership rejection. Named by ``local_id`` — the caller's own raw
        name — never the composed store key it never chose (DES-086).
        """
        if not self._display.scene_roots(composed):
            return OpError(code="not_found", reason=f"scene {local_id!r} not found")
        return OpError(
            code="rejected", reason=f"scene {local_id!r} holds nothing you own"
        )
