"""HubSceneWriter — apply agent-driven scene changes to the authoritative store.

The Hub is the single authority for UI state; the ``update`` and ``clear`` MCP
tools mutate ``HubDisplay`` first, then the Hub re-pushes to the Display. This
writer owns that authoritative mutation.

The write path asks the store's ``WriteSeam`` to realize each mutation through
the ``FieldRealization`` contract — an ABC element patched in place. A patch that
would leave an element invalid, is not owned, or names a forbidden or unknown
field is rejected in full, store untouched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.patch_batch import PatchBatch
from punt_lux.domain.hub.write_errors import (
    ImmutableFieldError,
    MalformedPatchError,
)
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected, WriteResult
from punt_lux.domain.update import RemoveElement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.hub.field_realization import FieldRealization
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubSceneWriter", "SceneScope"]

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SceneScope:
    """The ``(connection, scene)`` pair every ``update`` mutation is scoped to."""

    connection_id: ConnectionId
    scene_id: SceneId

    def removal(self, element_id: ElementId) -> RemoveElement:
        """Return the ``RemoveElement`` for ``element_id`` scoped to this scene."""
        return RemoveElement(scene_id=self.scene_id, element_id=element_id)


@final
class HubSceneWriter:
    """Apply ``update`` / ``clear`` mutations to the authoritative ``HubDisplay``.

    Stateless beyond its store reference; the caller re-pushes after a successful
    write, and the writer never talks to the Display.
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

        Stage a realization per field patch, guard every removal, check every
        rejection, and — only if all pass — commit the fields atomically (a
        mid-commit raise rolls all back), then apply removals post-commit
        (idempotent, see :meth:`_apply_removals`). Any rejection leaves the store
        untouched.
        """
        scope = SceneScope(connection_id, scene_id)
        # One store-lock hold spans the whole batch so the replicator never
        # snapshots it half-applied; reentrant, so nested writes re-enter freely.
        with self._display.write_lock():
            try:
                batch = PatchBatch.from_wire(patches)
                realizations = self._field_realizations(scope, batch)
                self._guard_removals(scope, batch.removals)
            except (
                MalformedPatchError,
                ImmutableFieldError,
                StructuralFieldWriteError,
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
        """Remove every element the connection owns, keeping it registered.

        Owner-scoped, unlike a re-show (whole-scene regardless of owner): a root
        another connection holds in a shared scene stays, and removing a root drops
        its subtree so a co-owned child is an idempotent no-op. A scene left empty
        has its frame forgotten (bounding the frame map under a churning-id clear);
        one a survivor still holds keeps its frame for the next re-push.
        """
        touched: set[SceneId] = set()
        with self._display.write_lock():
            for scene_id, element_id in self._display.elements_owned_by(connection_id):
                touched.add(scene_id)
                removal = RemoveElement(scene_id=scene_id, element_id=element_id)
                self._display.apply(connection_id, removal)
            for scene_id in touched:
                if not self._display.scene_roots(scene_id):
                    self._display.frames.forget(scene_id)

    def _field_realizations(
        self, scope: SceneScope, batch: PatchBatch
    ) -> list[FieldRealization]:
        """Resolve one owner-checked field realization per field patch."""
        seam = self._display.write_seam
        realizations: list[FieldRealization] = []
        for patch in batch.field_patches:
            self._require_owner(scope, patch.element_id)
            realizations.append(
                seam.field_realization(scope.scene_id, patch.element_id, patch.fields)
            )
        return realizations

    def _guard_removals(self, scope: SceneScope, removals: Sequence[ElementId]) -> None:
        """Owner-check each present removal.

        An absent target is skipped, not rejected, because ``RemoveElement`` is
        idempotent — but the skip is logged so a mistyped id (``submit-buton``
        for ``submit-button``) leaves a diagnosable trace rather than vanishing.
        """
        seam = self._display.write_seam
        for element_id in removals:
            if not seam.is_present(scope.scene_id, element_id):
                _log.debug(
                    "remove skipped: element %s absent in scene %s (idempotent no-op)",
                    element_id,
                    scope.scene_id,
                )
                continue
            self._require_owner(scope, element_id)

    @staticmethod
    def _commit(realizations: Sequence[FieldRealization]) -> None:
        """Commit every realization atomically.

        Each snapshots its own undo state, so a mid-batch raise rolls all back.
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
        """Evict each removed element from the store after all sets have committed.

        Post-commit phase. Staging alone does not make it infallible: when a batch
        removes both a parent and a child, evicting the parent's subtree already
        drops the child, so the child's own removal reaches an absent id. The apply
        path stays safe by idempotency, not by staging — ``_owners.get`` returns
        ``None`` so the ownership check returns without raising, and ``discard``
        no-ops on already-dropped storage.

        Removing the last root empties the scene; the scene's presentation is kept
        so a later resend blanks it into the frame it was shown in.
        """
        for element_id in removals:
            self._display.apply(scope.connection_id, scope.removal(element_id))

    def _require_owner(self, scope: SceneScope, element_id: ElementId) -> None:
        """Raise unless the scope's connection owns an installed ``element_id``.

        ``owner_of`` raises ``UnknownElementError`` for a never-installed element.
        """
        owner = self._display.owner_of(scope.scene_id, element_id)
        if owner != scope.connection_id:
            raise HubOwnershipError(
                scene_id=scope.scene_id,
                element_id=element_id,
                attempting=scope.connection_id,
                owning=owner,
            )
