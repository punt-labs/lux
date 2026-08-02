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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.domain.event_payload import EventPayload
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.wire_value import WireValue

__all__ = ["ButtonClicked", "ValueChanged"]


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
        # dataclass(slots=True) re-class quirk: the synthesized slots class is
        # a distinct object from the one the __class__ cell captured, so super()
        # resolves with the old type and rejects the new cls argument.
        self = object.__new__(cls)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "element_id", element_id)
        object.__setattr__(self, "owner_id", owner_id)
        return self

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the click event from a wire payload; the value is vestigial.

        A click carries no payload of its own — the interaction *is* the event —
        so ``value`` is accepted and ignored. Kept in the signature so every
        wire event shares one construction shape (see the ``WireEvent`` protocol).
        """
        _ = value  # payload-less event; the shared WireEvent signature carries it
        return cls(scene_id=scene_id, element_id=element_id, owner_id=owner_id)

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity alone — a click carries no data."""
        return EventPayload.of(self, self.kind).to_mapping()


@dataclass(frozen=True, slots=True, init=False)
class ValueChanged:
    """A typed value-change event for inputs (checkbox, slider, etc.).

    Same construction pattern as ``ButtonClicked`` — ``init=False``, ``__new__``
    the sole path — and carries the input's new ``value``.
    """

    scene_id: SceneId
    element_id: ElementId
    owner_id: ClientId
    # PY-TS-14 OK: the payload is discriminated by the firing element's kind —
    # checkbox→bool, input_text→str, color_picker→str (a hex color), slider→float
    # (int for the integer variant).
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

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the value-change event; the payload must be a JSON scalar.

        The whole value-input family (checkbox, input_text, slider, combo, …)
        fires ``ValueChanged``, so the shape it insists on is stated here once.
        The precise per-kind shape — a checkbox's ``bool``, a combo's index
        ``int`` — is the firing element's own invariant, enforced when its setter
        applies the patch, not re-encoded per element here.
        """
        return cls(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            value=WireValue(value, scene_id=scene_id, element_id=element_id).as_scalar(
                "a scalar value_changed payload (bool, int, float, or str)"
            ),
        )

    def to_payload(self) -> Mapping[str, object]:
        """Return the published payload: identity plus the input's new ``value``."""
        return EventPayload.of(self, self.kind).to_mapping(value=self.value)
