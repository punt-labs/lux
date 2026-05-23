"""Interaction sum type — user-driven events arriving at the domain boundary.

An ``Interaction`` is the dual of an ``Update``: where ``Update`` carries an
agent-initiated state change, ``Interaction`` carries a user-initiated event
(a click, a value drag, a text edit).  ``Display.interact`` validates the
interaction and emits the corresponding ``Event`` to subscribers; the
ownership and existence checks mirror ``Display.apply``.

PR 2 lands the first variant — ``ButtonClicked`` — to give wire-side
``ButtonRenderer`` a real domain destination for click events.  Additional
input kinds will join the union as later PRs migrate their renderers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain._wire_fields import WireFields
from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["ButtonClicked", "Interaction"]


@dataclass(frozen=True, slots=True)
class ButtonClicked:
    """The user clicked a ButtonElement in a scene."""

    scene_id: SceneId
    element_id: ElementId
    kind: ClassVar[Literal["button_clicked"]] = "button_clicked"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scene_id": str(self.scene_id),
            "element_id": str(self.element_id),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        fields = WireFields(d, "ButtonClicked")
        return cls(
            scene_id=SceneId(fields.require_str("scene_id")),
            element_id=ElementId(fields.require_str("element_id")),
        )


# Discriminated union the Display accepts via ``interact()``.  Adding a kind
# in a later PR extends this alias and gains a branch in Display.interact's
# match statement (with assert_never, per PY-EH-8).
type Interaction = ButtonClicked
