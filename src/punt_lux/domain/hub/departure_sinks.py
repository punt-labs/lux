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
        parameter however it likes.
        """
        ...


@final
class DepartureSinks:
    """At-most-one departure sink per connection, bound at connect time.

    Most connections have no transport-owned side state to release — a
    ``cli``-kind session never binds an inbox writer, for one — so
    :meth:`fire` on an unbound connection id is a documented no-op, not an
    error. Raising there would mean one connection with nothing to clean up
    blocks an entire swept set from departing behind it.
    """

    _sinks: dict[ConnectionId, DepartureSink]
    __slots__ = ("_sinks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._sinks = {}
        return self

    def bind(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        """Make ``sink`` the connection's departure cleanup. Idempotent overwrites."""
        self._sinks[connection_id] = sink

    def drop(self, connection_id: ConnectionId) -> None:
        """Unbind the connection's sink without firing it. No-op if absent."""
        self._sinks.pop(connection_id, None)

    def fire(self, connection_id: ConnectionId) -> None:
        """Run and unbind the connection's departure sink. No-op if none bound.

        Firing also unbinds — a departed connection's sink has done its one
        job, and leaving it bound forever would leak exactly the kind of
        unbounded per-connection state this class exists to release.
        """
        sink = self._sinks.pop(connection_id, None)
        if sink is not None:
            sink(connection_id)
