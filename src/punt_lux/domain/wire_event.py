"""``WireEvent`` — the contract an event that crossed the wire answers to.

An interaction the Display forwards arrives as an untyped value plus the triple
naming where it happened. The event class turns that into itself
(``from_wire``), reads the triple back to any caller that holds it, and says
what a ``publish``-decorated handler announces for it (``to_payload``). Kept
apart from the bare ``Event`` marker because this is a real contract with four
members, while ``Event`` is an identity with none.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from punt_lux.domain.event_protocol import Event

if TYPE_CHECKING:
    from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["WireEvent"]


@runtime_checkable
class WireEvent(Event, Protocol):
    """An ``Event`` that constructs itself from a remote invocation's payload.

    The typed-event constructor and its value-shape validation live on the event
    class, so a value-input family kind (checkbox, slider, combo, …) shares one
    ``ValueChanged.from_wire`` rather than each element re-encoding the shape. A
    ``RemoteDispatchSpec`` names its ``WireEvent`` type; the owning element asks
    the matched spec to build the event, and the spec delegates here. Construction
    raises ``WrongKindError`` when the payload's shape does not fit the event.

    Every wire event carries the identifying triple (scene, element, owner), so
    a caller that fires one can read those back without narrowing to a concrete
    event type. Each concrete event also carries its own ``kind`` ClassVar (the
    wire tag), but that is left off this protocol so ``isinstance`` narrowing to
    a concrete event stays sound — a narrow ``Literal`` kind would otherwise read
    as incompatible with a broad protocol ClassVar.
    """

    @property
    def scene_id(self) -> SceneId:
        """Return the scene the interaction targeted."""
        ...

    @property
    def element_id(self) -> ElementId:
        """Return the element the interaction targeted."""
        ...

    @property
    def owner_id(self) -> ClientId:
        """Return the client that owns the targeted element."""
        ...

    @classmethod
    def from_wire(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> Self:
        """Build the typed event from a wire payload, validating its shape."""
        ...

    def to_payload(self) -> Mapping[str, object]:
        """Return what a ``publish``-decorated handler announces for this event.

        The publish leg carries the event's data, so the event — not the
        decorator — decides what that data is: an ``EventPayload`` identity
        (kind, scene, element) plus whatever the event itself carries.
        """
        ...
