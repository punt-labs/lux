"""Update sum type — the three mutation requests the domain accepts in PR 1.

PR 1 covers what the ``basics`` family needs: ``AddElement`` (insert),
``RemoveElement`` (delete), ``SetProperty`` (mutate one typed field).
``ReparentElement`` and ``ReplaceElement`` join in later PRs when the
``layout`` family lands.

Each kind owns its codec — ``to_dict`` instance method, ``from_dict``
classmethod — per PY-OO-5 and PY-OO-7. The ``Update`` type alias is the
discriminated union the ``Display`` accepts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self, cast

from punt_lux.domain.element import Element
from punt_lux.domain.ids import ElementId, SceneId

__all__ = [
    "AddElement",
    "ElementDecoder",
    "RemoveElement",
    "SetProperty",
    "Update",
]


# Element decoder is provided by the caller — the protocol/elements/ codec
# registry — to break what would otherwise be a circular import from
# domain → protocol. Domain owns the contract; protocol owns the wire dispatch.
type ElementDecoder = Callable[[Mapping[str, object]], Element]


def _require_str(d: Mapping[str, object], field: str) -> str:
    """Return ``d[field]`` as a non-empty str or raise."""
    raw = d.get(field)
    if not isinstance(raw, str) or not raw:
        msg = f"Update field {field!r} must be a non-empty str, got {raw!r}"
        raise ValueError(msg)
    return raw


def _require_mapping(d: Mapping[str, object], field: str) -> Mapping[str, object]:
    """Return ``d[field]`` as a mapping or raise."""
    raw = d.get(field)
    if not isinstance(raw, Mapping):
        msg = f"Update field {field!r} must be a mapping, got {type(raw).__name__}"
        raise ValueError(msg)
    return cast("Mapping[str, object]", raw)


@dataclass(frozen=True, slots=True)
class AddElement:
    """Insert an element into a scene under an optional parent."""

    scene_id: SceneId
    element: Element
    # parent_id is the documented absence — top-level elements have no parent.
    parent_id: ElementId | None = None
    kind: ClassVar[Literal["add_element"]] = "add_element"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element": self.element.to_dict(),
        }
        if self.parent_id is not None:
            payload["parent_id"] = str(self.parent_id)
        return payload

    @classmethod
    def from_dict(
        cls,
        d: Mapping[str, object],
        *,
        decode_element: ElementDecoder,
    ) -> Self:
        scene_id = SceneId(_require_str(d, "scene_id"))
        element = decode_element(_require_mapping(d, "element"))
        raw_parent = d.get("parent_id")
        parent_id: ElementId | None
        if raw_parent is None:
            parent_id = None
        elif isinstance(raw_parent, str) and raw_parent:
            parent_id = ElementId(raw_parent)
        else:
            msg = f"AddElement.parent_id must be str or absent, got {raw_parent!r}"
            raise ValueError(msg)
        return cls(scene_id=scene_id, element=element, parent_id=parent_id)


@dataclass(frozen=True, slots=True)
class RemoveElement:
    """Remove an element (and its subtree) from a scene."""

    scene_id: SceneId
    element_id: ElementId
    kind: ClassVar[Literal["remove_element"]] = "remove_element"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(
            scene_id=SceneId(_require_str(d, "scene_id")),
            element_id=ElementId(_require_str(d, "element_id")),
        )


@dataclass(frozen=True, slots=True)
class SetProperty:
    """Change one typed property on an existing element."""

    scene_id: SceneId
    element_id: ElementId
    field: str
    value: object
    kind: ClassVar[Literal["set_property"]] = "set_property"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
            "field": self.field,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(
            scene_id=SceneId(_require_str(d, "scene_id")),
            element_id=ElementId(_require_str(d, "element_id")),
            field=_require_str(d, "field"),
            value=d.get("value"),
        )


# Discriminated union the Display accepts. Adding a kind in a later PR
# extends this alias and gains a branch in Display.apply's match statement.
type Update = AddElement | RemoveElement | SetProperty
