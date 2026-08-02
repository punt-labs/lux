"""Ports the callback router depends on — the live-session read and a leg's wake.

The router decides where a click goes, and it needs two things it does not own to
decide: which sessions are still in lease, and how to nudge a session that is
holding a live connection. Both arrive as structural ports so the routing is
tested against fakes rather than a client registry and a socket:

- ``LiveSessions`` — the sessions whose lease has not lapsed (the Hub's client
  registry), read before the router's lock so the two never nest.
- ``CallbackListener`` — a persistent leg's payload-less wake, registered for as
  long as its connection lives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackListener", "LiveSessions"]


@runtime_checkable
class LiveSessions(Protocol):
    """The live-session read the router routes against — the sessions still in lease."""

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return the sessions whose lease has not lapsed, sweeping the expired."""
        ...


@runtime_checkable
class CallbackListener(Protocol):
    """A persistent leg's wake: 'a routed invocation landed — drain and push it.'

    Payload-less by design, like the replicator's menu flag: the leg reads the hold
    itself on waking, so the wake carries no state the hold does not already own.
    """

    def wake(self) -> None:
        """Signal that a routed invocation is waiting for this connection."""
        ...
