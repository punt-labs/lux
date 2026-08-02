"""RemoteDispatchSpec — one interactive event an Element routes to the Hub.

An interactive Element returns a tuple of these from ``_remote_dispatch_specs``.
The spec carries an interaction's full contract: the wire ``event_kind`` tag it
answers to, and — through its ``WireEvent`` type — the value-shape validation and
typed-event constructor. ``wrap_handlers_for_remote`` reads the spec to collapse
a handler bucket into one ``RemoteEventHandlerInvocation`` on the Display side;
the Hub reads it to build the typed event from an inbound invocation
(``build_event``). A new interactive kind declares a spec instead of a central
dispatcher growing another branch (PY-IC-7), so the kind knowledge lives once on
the owning element and its event class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.event_kinds import EventKind
    from punt_lux.domain.ids import ClientId, ElementId, SceneId
    from punt_lux.domain.wire_event import WireEvent

__all__ = ["RemoteDispatchSpec"]


@dataclass(frozen=True, slots=True)
class RemoteDispatchSpec:
    """The event type, action, and wire kind for one remote-dispatched event.

    ``action`` is ``str | None``: None means "fall back to the element id",
    the documented default the wrap loop applies when building the
    invocation (a button with no explicit action dispatches under its id).
    """

    event_type: type[WireEvent]
    action: str | None
    event_kind: EventKind

    def build_event(
        self,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ClientId,
        value: object,
    ) -> WireEvent:
        """Construct this spec's typed event from a wire payload.

        Delegates to the event class's ``from_wire``, which owns the value-shape
        validation and raises ``WrongKindError`` on a payload that does not fit.
        """
        return self.event_type.from_wire(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=owner_id,
            value=value,
        )
