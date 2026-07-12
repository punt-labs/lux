"""HubSceneWriter — apply agent-driven scene changes to the authoritative store.

The Hub is the single authority for UI state; the ``update`` and ``clear`` MCP
tools must mutate ``HubDisplay`` first, then the Hub re-pushes to the Display.
This writer owns that authoritative mutation: it parses the field patches and
removals a client submits through ``update``, and empties a client's scenes on
``clear``. Each field patch is checked against its own element's self-validation
before anything is written — an update that would leave an element invalid, or
targets an element the caller does not own or that is not patchable, is rejected
in full and the store is left untouched.

Patch validation is component-local: each element validates its own post-patch
state (per-element ``validate()``), not a whole-tree walk the way ``show`` gates
a fresh tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.patch_batch import FieldPatch, PatchBatch
from punt_lux.domain.hub.patch_errors import MalformedPatchError, NotPatchableError
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected, WriteResult
from punt_lux.domain.update import RemoveElement

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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

        The single authoritative mutation for ``update``: parse the wire patches,
        validate every field patch on a copy, and — only if all pass — commit the
        sets atomically and apply the removals. On any rejection the store is
        untouched and the caller re-pushes nothing. This runs exactly once and is
        never placed inside a retryable region, so a failed re-push can never
        re-drive the mutation against an already-mutated store.
        """
        scope = SceneScope(connection_id, scene_id)
        try:
            batch = PatchBatch.from_wire(patches)
            targets = self._resolve(scope, batch)
        except (
            MalformedPatchError,
            NotPatchableError,
            HubOwnershipError,
            UnknownElementError,
            UnknownSceneError,
        ) as exc:
            return WriteRejected(str(exc))
        for element, field_patch in targets:
            rejection = field_patch.rejection_against(element)
            if rejection is not None:
                return rejection
        self._commit_sets(targets)
        self._apply_removals(scope, batch.removals)
        return WriteAccepted()

    def clear(self, connection_id: ConnectionId) -> None:
        """Remove every scene the connection owns, keeping it registered.

        Replaces each owned scene with an empty root set through the same
        authoritative path ``show`` uses for a re-show, so ownership records and
        child indexes unwind exactly as they do on a normal scene replacement.
        """
        scenes = {
            scene_id for scene_id, _ in self._display.elements_owned_by(connection_id)
        }
        for scene_id in scenes:
            self._display.replace_scene(connection_id, scene_id, ())

    def _resolve(
        self, scope: SceneScope, batch: PatchBatch
    ) -> list[tuple[AbcElement, FieldPatch]]:
        """Resolve every set target and check ownership of every removal.

        Raises the matching typed error on the first not-owned, not-installed, or
        not-patchable id, so the caller rejects the whole batch before any write.
        """
        targets = [
            (self._patchable(scope, fp.element_id), fp) for fp in batch.field_patches
        ]
        for element_id in batch.removals:
            self._require_owner(scope, element_id)
        return targets

    def _apply_removals(self, scope: SceneScope, removals: Sequence[ElementId]) -> None:
        """Evict each removed element from the store after all sets have committed."""
        for element_id in removals:
            self._display.apply(
                scope.connection_id,
                RemoveElement(scene_id=scope.scene_id, element_id=element_id),
            )

    @staticmethod
    def _commit_sets(targets: Sequence[tuple[AbcElement, FieldPatch]]) -> None:
        """Write every validated field patch to its live element, atomically.

        Snapshots each target's state before the first write and restores all on
        any raise, so a mid-batch failure can never leave a partial commit — the
        whole update is rejected and the store is untouched. A raise here is
        unexpected (every patch already validated on a copy), so it propagates as
        a bug after the rollback rather than being swallowed.
        """
        snapshots = [(element, dict(vars(element))) for element, _ in targets]
        try:
            for element, field_patch in targets:
                field_patch.commit_to(element)
        except Exception:
            for element, snapshot in snapshots:
                vars(element).clear()
                vars(element).update(snapshot)
            raise

    def _patchable(self, scope: SceneScope, element_id: ElementId) -> AbcElement:
        """Resolve an owned, mutable ABC element, or raise the matching error."""
        self._require_owner(scope, element_id)
        element = self._display.resolve(scope.scene_id, element_id)
        if not isinstance(element, AbcElement):
            raise NotPatchableError(scene_id=scope.scene_id, element_id=element_id)
        return element

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
