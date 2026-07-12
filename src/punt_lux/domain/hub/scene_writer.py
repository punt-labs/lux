"""HubSceneWriter — apply agent-driven scene changes to the authoritative store.

The Hub is the single authority for UI state; the ``update`` and ``clear`` MCP
tools must mutate ``HubDisplay`` first, then the Hub re-pushes to the Display.
This writer owns that authoritative mutation: it applies the field patches and
removals a client submits through ``update``, and empties a client's scenes on
``clear``. Field patches are validated against each element's own
self-validation the same way ``show`` gates a fresh tree — an update that would
leave an element invalid is rejected in full and nothing is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.ids import ElementId
from punt_lux.domain.update import RemoveElement
from punt_lux.domain.validation import ValidationReport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId, SceneId

__all__ = ["FieldPatch", "HubSceneWriter", "PatchBatch"]


@dataclass(frozen=True, slots=True)
class FieldPatch:
    """A ``set`` request from ``update``: the fields to write onto one element."""

    element_id: ElementId
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PatchBatch:
    """One ``update`` call split into its field-set and removal requests.

    ``from_wire`` is the single place the raw agent patch list — dicts with
    ``id`` plus ``set`` or ``remove`` — becomes typed domain requests, so the
    tool layer never hand-parses the wire shape.
    """

    field_patches: tuple[FieldPatch, ...]
    removals: tuple[ElementId, ...]

    @classmethod
    def from_wire(cls, patches: Sequence[Mapping[str, object]]) -> Self:
        """Build a batch from the ``update`` tool's raw patch dicts."""
        field_patches: list[FieldPatch] = []
        removals: list[ElementId] = []
        for patch in patches:
            element_id = ElementId(str(patch["id"]))
            if patch.get("remove", False):
                removals.append(element_id)
            elif isinstance(fields := patch.get("set"), Mapping):
                field_patches.append(
                    FieldPatch(element_id, cast("Mapping[str, object]", fields))
                )
        return cls(tuple(field_patches), tuple(removals))


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

    def apply_patches(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        batch: PatchBatch,
    ) -> str | None:
        """Write ``batch`` to the authoritative store, or reject it whole.

        Returns an agent-facing rejection reason, or ``None`` on success. Every
        field patch is validated on a copy first: if any would leave its element
        invalid — or targets an element the caller does not own or that is not
        patchable — the whole update is rejected and the store is untouched.
        Removals apply only once every field patch has validated, so a rejected
        set never leaves a half-applied update behind.
        """
        try:
            targets = [
                (self._patchable(connection_id, scene_id, fp.element_id), fp.fields)
                for fp in batch.field_patches
            ]
            for element_id in batch.removals:
                self._require_owner(connection_id, scene_id, element_id)
        except (
            HubOwnershipError,
            UnknownElementError,
            UnknownSceneError,
            TypeError,
        ) as exc:
            return str(exc)
        for element, fields in targets:
            rejection = self._rejection_for(element, fields)
            if rejection is not None:
                return rejection
        for element, fields in targets:
            element.apply_patch(fields)
        for element_id in batch.removals:
            self._display.apply(
                connection_id,
                RemoveElement(scene_id=scene_id, element_id=element_id),
            )
        return None

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

    def _patchable(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> AbcElement:
        """Resolve an owned, mutable ABC element, or raise the matching error."""
        self._require_owner(connection_id, scene_id, element_id)
        element = self._display.resolve(scene_id, element_id)
        if not isinstance(element, AbcElement):
            msg = (
                f"element {str(element_id)!r} in scene {str(scene_id)!r} "
                f"is not patchable"
            )
            raise TypeError(msg)
        return element

    def _require_owner(
        self,
        connection_id: ConnectionId,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> None:
        """Raise unless ``connection_id`` owns an installed ``element_id``.

        ``owner_of`` raises ``UnknownElementError`` when the element was never
        installed, so a patch or removal aimed at a stale id fails loud rather
        than becoming a silent no-op.
        """
        owner = self._display.owner_of(scene_id, element_id)
        if owner != connection_id:
            raise HubOwnershipError(
                scene_id=scene_id,
                element_id=element_id,
                attempting=connection_id,
                owning=owner,
            )

    @staticmethod
    def _rejection_for(element: AbcElement, fields: Mapping[str, object]) -> str | None:
        """Return why ``fields`` may not be written to ``element``, or ``None``.

        Applies the patch to a throwaway copy so the live element is never
        touched by a rejected write. A setter that refuses a bad value and a
        self-validation failure both surface here as the agent-facing reason,
        rendered the same way ``show`` renders a rejected tree.
        """
        try:
            errors = deepcopy(element).apply_patch(fields).validate()
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            return str(exc)
        if errors:
            return ValidationReport(errors).describe()
        return None
