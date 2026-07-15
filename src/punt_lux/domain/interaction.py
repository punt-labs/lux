"""Typed interaction events dispatched through ``Element.fire``.

Each event carries the three identifying fields (scene, element, owner)
and a ``kind`` discriminator. Constructed by any tier that needs to fire
the event — the Display constructs it via the renderer; the Hub
constructs it in ``Display.interact``.

Upstream of ``Display.interact`` lives wire-shape triage in the pump;
downstream lives typed handler dispatch through ``Element.fire``. No
intermediate sum type stands between the inbound
``RemoteEventHandlerInvocation`` and the typed event the dispatcher
hands to the per-Element handler registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["ButtonClicked", "EventKind", "ValueChanged"]

type EventKind = Literal[
    "button_clicked", "value_changed", "tab_changed", "header_toggled"
]


@dataclass(frozen=True, slots=True, init=False)
class ButtonClicked:
    """A typed button-click event.

    The frozen-slots dataclass holds the three identifying fields plus a
    ``kind`` discriminator. ``init=False`` disables the synthesized
    ``__init__`` so ``__new__`` is the only construction path; field
    writes go through ``object.__setattr__`` because the synthesized
    ``__setattr__`` raises ``FrozenInstanceError`` after construction.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    kind: ClassVar[Literal["button_clicked"]] = "button_clicked"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
    ) -> Self:
        # ``object.__new__`` (not ``super().__new__``) avoids the
        # dataclass(slots=True) re-class quirk: the synthesized slots
        # class is a distinct object from the one the __class__ cell
        # captured at method-definition time, so super() resolves with
        # the old type and rejects the new cls argument.
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        return self


@dataclass(frozen=True, slots=True, init=False)
class ValueChanged:
    """A typed value-change event for inputs (checkbox, slider, etc.).

    Same construction pattern as ``ButtonClicked`` — ``init=False`` with
    ``__new__`` as the sole construction path. Carries a ``value`` payload
    representing the new state of the input element.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    # PY-TS-14 OK: the payload is discriminated by the firing element's kind —
    # checkbox→bool, input_text→str, slider→float (int for the integer variant).
    value: bool | int | float | str
    kind: ClassVar[Literal["value_changed"]] = "value_changed"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: bool | int | float | str,
    ) -> Self:
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "value", value)
        return self
