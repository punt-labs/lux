"""OwnershipError — refused mutation due to client/element ownership mismatch.

Per PY-EH-1, ownership is validated at the boundary before any state
mutation. This is a typed Error value describing an ownership refusal
as data (per PY-EH-8's discriminated-union-of-outcomes shape), distinct
from ``HubOwnershipError`` (``domain.hub.ownership_error``), the
exception ``HubDisplay.apply`` actually raises on the same refusal
today.
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
