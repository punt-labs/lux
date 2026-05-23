"""Events emitted by ``Display.interact`` when a user interaction succeeds.

Sibling of ``domain.event`` (which holds the Element-mutation events).
The split exists because PY-OO-2 caps a module at 3 classes — element
events already fill the budget — and because user-interaction events
have a distinct origin (the wire boundary) from state-mutation events
(an agent-issued Update).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["ButtonPressed"]


@dataclass(frozen=True, slots=True)
class ButtonPressed:
    """The Interaction was applied: a ButtonElement received a user click."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    kind: ClassVar[Literal["button_pressed"]] = "button_pressed"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "owner_id": str(self.owner_id),
        }
