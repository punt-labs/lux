"""Success Events emitted by Display.apply when a state change is applied.

Failure responses live alongside in ``domain.error``; together they form
the ``Result`` returned by ``Display.apply`` (see ``domain.result``).
``Display.apply`` never returns ``None`` — PY-EH-8.

PR 2 split the family: state-mutation events stay here, while
``ButtonPressed`` (emitted by ``Display.interact``) lives in
``domain.interaction_event``.  This module re-exports it so the
``Event`` union remains a single name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction_event import ButtonPressed

__all__ = [
    "ButtonPressed",
    "ElementAdded",
    "ElementRemoved",
    "ElementUpdated",
    "Event",
]


@dataclass(frozen=True, slots=True)
class ElementAdded:
    """The Update was applied: a new element joined the scene."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    # parent_id is the documented absence — top-level elements have no parent.
    parent_id: ElementId | None = None
    kind: ClassVar[Literal["element_added"]] = "element_added"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "owner_id": str(self.owner_id),
        }
        if self.parent_id is not None:
            payload["parent_id"] = str(self.parent_id)
        return payload


@dataclass(frozen=True, slots=True)
class ElementRemoved:
    """The Update was applied: an element left the scene."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    kind: ClassVar[Literal["element_removed"]] = "element_removed"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "owner_id": str(self.owner_id),
        }


@dataclass(frozen=True, slots=True)
class ElementUpdated:
    """The Update was applied: an element field changed."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    field: str
    old_value: object
    new_value: object
    kind: ClassVar[Literal["element_updated"]] = "element_updated"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "owner_id": str(self.owner_id),
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


# Discriminated union of success events.
type Event = ElementAdded | ElementRemoved | ElementUpdated | ButtonPressed
