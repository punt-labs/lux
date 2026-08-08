"""Typed lookup / validation failure values, described as data per PY-EH-8.

Sibling classes of Events, not exceptions. ``HubDisplay.apply`` today
enforces these same failures by raising rather than returning one of
these values; ``DuplicateIdError`` is the one member of this family
still live in production, returned by ``DuplicateIdScanner``
(``domain.id_uniqueness``) rather than by ``apply`` itself.

Three lookup/validation kinds live here:

- ``DuplicateIdError`` — AddElement targeted an id already in use.
- ``UnknownElementError`` — RemoveElement/SetProperty targeted an
  element id that does not exist.
- ``PropertyTypeError`` — SetProperty's value does not match the
  declared type of the target field.

OwnershipError lives in ``domain.ownership`` (its own module to keep
``classes_per_module`` within the OO target).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.domain.ownership import OwnershipError

__all__ = [
    "DuplicateIdError",
    "Error",
    "PropertyTypeError",
    "UnknownElementError",
]


@dataclass(frozen=True, slots=True)
class DuplicateIdError:
    """AddElement targeted an id that already exists in the scene."""

    scene_id: SceneId
    element_id: ElementId
    kind: ClassVar[Literal["duplicate_id_error"]] = "duplicate_id_error"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
        }


@dataclass(frozen=True, slots=True)
class PropertyTypeError:
    """SetProperty's value does not match the element field's declared type."""

    scene_id: SceneId
    element_id: ElementId
    field: str
    expected_type: str
    got_value: object
    kind: ClassVar[Literal["property_type_error"]] = "property_type_error"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "field": self.field,
            "expected_type": self.expected_type,
            "got_value": self.got_value,
        }


@dataclass(frozen=True, slots=True)
class UnknownElementError:
    """RemoveElement / SetProperty targeted an element id that does not exist."""

    scene_id: SceneId
    element_id: ElementId
    kind: ClassVar[Literal["unknown_element_error"]] = "unknown_element_error"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
        }


# Discriminated union of failure values, including OwnershipError from
# the sibling module.
type Error = OwnershipError | DuplicateIdError | PropertyTypeError | UnknownElementError
