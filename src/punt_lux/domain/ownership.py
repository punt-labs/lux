"""OwnershipError — refused mutation due to client/element ownership mismatch.

Per PY-EH-1, ownership is validated at the boundary before any state
mutation. Per PY-EH-8, ``Display.apply`` returns this typed Error
instead of raising or returning ``None`` when a client attempts to
mutate an element it does not own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["OwnershipError"]


@dataclass(frozen=True, slots=True)
class OwnershipError:
    """The attempting client does not own the target element."""

    scene_id: SceneId
    element_id: ElementId
    attempting_client_id: ClientId
    owning_client_id: ClientId
    kind: ClassVar[Literal["ownership_error"]] = "ownership_error"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "attempting_client_id": str(self.attempting_client_id),
            "owning_client_id": str(self.owning_client_id),
        }
