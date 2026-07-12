"""HubSceneWriter — apply agent-driven scene changes to the authoritative store.

The Hub is the single authority for UI state; the ``update`` and ``clear`` MCP
tools mutate ``HubDisplay`` first, then the Hub re-pushes to the Display. This
writer owns that authoritative mutation.

The write path above the seam is branch-free: it asks the store's ``WriteSeam``
to realize each field mutation and treats the result uniformly through the
``FieldRealization`` contract, whether the target is an ABC element (patched in
place) or a legacy root (realized by ``dataclasses.replace`` and rebound). A
patch that would leave an element invalid, targets an element the caller does
not own, names an immutable (``id``/``kind``) or unknown field, or addresses a
legacy element nested below a legacy composite is rejected in full, store
untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.patch_batch import PatchBatch
from punt_lux.domain.hub.write_errors import (
    ImmutableFieldError,
    MalformedPatchError,
    NestedLegacyWriteError,
)
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected, WriteResult
from punt_lux.domain.update import RemoveElement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.hub.field_realization import FieldRealization
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubSceneWriter", "SceneScope"]


@dataclass(frozen=True, slots=True)
class SceneScope:
    """The ``(connection, scene)`` pair every ``update`` mutation is scoped to.

    Connection and scene always travel together through the write path, so they
    become one value object rather than a repeated parameter pair (PY-OO-3).
    """

    connection_id: ConnectionId
    scene_id: SceneId


@final
class HubSceneWriter:
    """Apply ``update`` / ``clear`` mutations to the authoritative ``HubDisplay``.

    Stateless beyond its store reference. The caller re-pushes the affected
    scene after a successful write; the writer never talks to the Display.
    """

    _display: HubDisplay
    __slots__ = ("_display",)

    def __new__(cls, display: HubDisplay) -> Self:
        self = super().__new__(cls)
        self._display = display
        return self

    def apply(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        patches: Sequence[Mapping[str, object]],
    ) -> WriteResult:
        """Parse and write ``patches`` to the store once, or reject the batch whole.

        Parse the wire patches, stage a realization per field patch, check every
        rejection, and — only if all pass — commit the realizations atomically
        and apply the removals. On any rejection the store is untouched and the
        caller re-pushes nothing. This runs exactly once, never inside a
        retryable region, so a failed re-push can never re-drive the mutation.
        """
        scope = SceneScope(connection_id, scene_id)
        try:
            batch = PatchBatch.from_wire(patches)
            realizations = self._stage(scope, batch)
        except (
            MalformedPatchError,
            ImmutableFieldError,
            NestedLegacyWriteError,
            HubOwnershipError,
            UnknownElementError,
            UnknownSceneError,
        ) as exc:
            return WriteRejected(str(exc))
        for realization in realizations:
            rejection = realization.rejection()
            if rejection is not None:
                return rejection
        self._commit(realizations)
        self._apply_removals(scope, batch.removals)
        return WriteAccepted()

    def clear(self, connection_id: ConnectionId) -> None:
        """Remove every scene the connection owns, keeping it registered.

        Replaces each owned scene with an empty root set through the same
        authoritative path ``show`` uses for a re-show, so ownership records and
        child indexes unwind exactly as they do on a normal scene replacement.
        """
        owned = self._display.elements_owned_by(connection_id)
        for scene_id in {scene_id for scene_id, _ in owned}:
            self._display.replace_scene(connection_id, scene_id, ())

    def _stage(self, scope: SceneScope, batch: PatchBatch) -> list[FieldRealization]:
        """Resolve a realization per field patch; guard every removal.

        Checks ownership before the seam, then asks the store to realize each
        mutation — raising the matching typed error on the first not-owned,
        not-installed, immutable-field, or nested-legacy target, so the caller
        rejects the whole batch before any write.
        """
        seam = self._display.write_seam
        realizations: list[FieldRealization] = []
        for patch in batch.field_patches:
            self._require_owner(scope, patch.element_id)
            realizations.append(
                seam.field_realization(scope.scene_id, patch.element_id, patch.fields)
            )
        for element_id in batch.removals:
            self._require_owner(scope, element_id)
            seam.guard_removal(scope.scene_id, element_id)
        return realizations

    @staticmethod
    def _commit(realizations: Sequence[FieldRealization]) -> None:
        """Commit every realization, atomically.

        Each realization snapshots its own undo state as it commits, so a
        mid-batch raise rolls back every realization already committed — the
        store untouched on failure. A raise here is unexpected (every
        realization already reported no rejection), so it propagates as a bug
        after the rollback rather than being swallowed.
        """
        committed: list[FieldRealization] = []
        try:
            for realization in realizations:
                realization.commit()
                committed.append(realization)
        except Exception:
            for realization in reversed(committed):
                realization.restore()
            raise

    def _apply_removals(self, scope: SceneScope, removals: Sequence[ElementId]) -> None:
        """Evict each removed element from the store after all sets have committed."""
        for element_id in removals:
            self._display.apply(
                scope.connection_id,
                RemoveElement(scene_id=scope.scene_id, element_id=element_id),
            )

    def _require_owner(self, scope: SceneScope, element_id: ElementId) -> None:
        """Raise unless the scope's connection owns an installed ``element_id``.

        ``owner_of`` raises ``UnknownElementError`` when the element was never
        installed, so a patch or removal aimed at a stale id fails loud rather
        than becoming a silent no-op.
        """
        owner = self._display.owner_of(scope.scene_id, element_id)
        if owner != scope.connection_id:
            raise HubOwnershipError(
                scene_id=scope.scene_id,
                element_id=element_id,
                attempting=scope.connection_id,
                owning=owner,
            )
