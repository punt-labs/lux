"""DepartureSinks — the transport-owned cleanup a connection's departure fires.

A departure releases Hub-side state (the registry entry, ownership,
subscriptions, the writer binding) unconditionally. Some transports also hold
state the Hub knows nothing about — today, only the MCP inbox queue
(:mod:`punt_lux.domain.hub.inbox`). :class:`DepartureSinks` is the seam: a
transport binds its own per-connection cleanup once, at connect time, and the
departure coordinator fires it once, at departure time, for every trigger
(graceful disconnect, the lease timer, or a live write's embedded sweep)
alike — the same one-coordinator discipline the registry-and-ownership legs
already have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

__all__ = ["DepartureSink", "DepartureSinks"]


@runtime_checkable
class DepartureSink(Protocol):
    """A transport's per-connection cleanup, run once on that connection's departure."""

    def __call__(self, connection_id: ConnectionId, /) -> None:
        """Release whatever the transport holds for ``connection_id``.

        Positional-only: :class:`DepartureSinks` always calls a sink
        positionally, so an implementation is free to name its own
        parameter however it likes. Runs inside the departure coordinator's
        ``StoreLock`` critical section, so a sink must be non-blocking and
        must never re-enter a Hub-mutating (``StoreLock``-taking) call.
        """
        ...


@final
class DepartureSinks:
    """The departure sinks a connection binds at connect time, fired on departure.

    A connection may hold more than one piece of transport-owned side state —
    an MCP session binds both its inbox queue and, once it owns a menu bar, its
    menu-registry entry — so each connection carries a *list* of sinks, fired in
    bind order on departure. Most connections have none — a ``cli``-kind session
    never binds an inbox writer — so :meth:`fire` on an unbound connection id is a
    documented no-op, not an error. Raising there would mean one connection with
    nothing to clean up blocks an entire swept set from departing behind it.
    """

    _sinks: dict[ConnectionId, list[DepartureSink]]
    __slots__ = ("_sinks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._sinks = {}
        return self

    def bind(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        """Add ``sink`` to the connection's departure cleanups. Idempotent per sink.

        A sink already bound for the connection is not added twice, so re-arming
        on each ``menu_set`` (or a same-identity reconnect) cannot grow the list
        without bound or fire one cleanup repeatedly.
        """
        bound = self._sinks.setdefault(connection_id, [])
        if sink not in bound:
            bound.append(sink)

    def drop(self, connection_id: ConnectionId) -> None:
        """Unbind the connection's sinks without firing them. No-op if absent."""
        self._sinks.pop(connection_id, None)

    def fire(self, connection_id: ConnectionId) -> None:
        """Run and unbind every sink bound for the connection. No-op if none.

        Firing also unbinds — a departed connection's sinks have done their one
        job, and leaving them bound forever would leak exactly the kind of
        unbounded per-connection state this class exists to release. Sinks run in
        the order they were bound.
        """
        for sink in self._sinks.pop(connection_id, ()):
            sink(connection_id)
