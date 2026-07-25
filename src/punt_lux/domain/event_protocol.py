"""Marker Protocol for events dispatched through ``Element.fire``.

The handler registry on the Element ABC is typed against this Protocol so
``add_handler(event_type, handler)`` rejects callers that mix event
families. Every interaction-event class (``ButtonClicked``, future
``SliderChanged``, ``TextEdited``, ...) satisfies it implicitly — the
Protocol carries no required members, only an identity.

The companion ``Handler[E]`` alias spells the callback shape every
factory in the per-Element handler catalogs must produce.

This Protocol is distinct from the success-event union in
``domain.event``. That union names the outcomes ``Display.apply`` /
``Display.interact`` return; this Protocol names the family of inputs
the per-Element registry dispatches.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import ClientId, ElementId, SceneId

__all__ = ["Event", "Handler", "WireEvent"]


@runtime_checkable
class Event(Protocol):
    """Marker Protocol for events dispatched through ``Element.fire``."""


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


type Handler[E: Event] = Callable[[E], None]
