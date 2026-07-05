"""RemoteDispatchSpec — one interactive event bucket an Element routes to the Hub.

An interactive Element returns a tuple of these from
``_remote_dispatch_specs`` so ``wrap_handlers_for_remote`` knows which
handler buckets the Display collapses into a single
``RemoteEventHandlerInvocation``. Bundling the three fields keeps new
interactive kinds additive: a kind declares its spec instead of the wrap
loop growing another ``isinstance`` branch (PY-IC-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.event_protocol import Event
    from punt_lux.domain.interaction import EventKind

__all__ = ["RemoteDispatchSpec"]


@dataclass(frozen=True, slots=True)
class RemoteDispatchSpec:
    """The event type, action, and kind for one remote-dispatched bucket.

    ``action`` is ``str | None``: None means "fall back to the element id",
    the documented default the wrap loop applies when building the
    invocation (a button with no explicit action dispatches under its id).
    """

    event_type: type[Event]
    action: str | None
    event_kind: EventKind
