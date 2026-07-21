"""The update request — a discriminated batch of element patches for one scene."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from punt_lux.domain.hub.patch_batch import PatchBatch
from punt_lux.domain.hub.write_errors import MalformedPatchError
from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["RemovePatch", "ScenePatch", "SetPatch", "UpdateRequest"]


class SetPatch(BaseModel):
    """Set fields on one element."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    # The fields to write; open per element kind, validated by the element codec
    # and setters inside the writer (PY-TS-14 wire boundary).
    set: dict[str, object]

    def to_wire(self) -> dict[str, object]:
        """Return the wire shape the writer consumes."""
        return {"id": self.id, "set": self.set}


class RemovePatch(BaseModel):
    """Remove one element from the scene."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str

    def to_wire(self) -> dict[str, object]:
        """Return the wire shape the writer consumes."""
        return {"id": self.id, "remove": True}


# A patch sets fields on an element or removes it — never both, never neither.
type ScenePatch = SetPatch | RemovePatch


class UpdateRequest(BaseModel):
    """A batch of element patches, each mapped to its typed variant.

    The wire patches carry no discriminator tag ({"id", "set"} or
    {"id", "remove": true}); ``parse`` maps each wire shape to its variant using
    the writer's own boundary codec, so a malformed shape is rejected with the
    exact wording ``HubSceneWriter`` would produce. The writer's ownership,
    field-legality, and structural rejections are unchanged and still run when
    the operation replays these patches.
    """

    model_config = ConfigDict(frozen=True)

    patches: list[ScenePatch]

    @classmethod
    def parse(cls, raw_patches: Sequence[object]) -> UpdateRequest | OpError:
        """Map wire shapes to variants, or return an ``OpError`` instead of raising.

        Shape validation delegates to ``PatchBatch.from_wire`` — the single
        boundary codec — so the rejection strings are byte-identical to the
        writer's, and same-id sets merge exactly as the writer merges them.
        """
        try:
            batch = PatchBatch.from_wire(list(raw_patches))
        except MalformedPatchError as exc:
            return OpError(code="invalid_request", reason=str(exc))
        patches: list[ScenePatch] = [
            SetPatch(id=str(patch.element_id), set=dict(patch.fields))
            for patch in batch.field_patches
        ]
        patches.extend(RemovePatch(id=str(element_id)) for element_id in batch.removals)
        return cls(patches=patches)

    def to_wire(self) -> list[dict[str, object]]:
        """Return the wire patches the writer replays."""
        return [patch.to_wire() for patch in self.patches]
