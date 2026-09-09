"""DepartureCascade — the subscriptions/writer/inbox tail of a departure.

``HubDisplay``'s own ``_depart``/``_depart_lapsed`` already run the
registry-and-ownership half of a departure atomically, under ``StoreLock``.
This collaborator sequences the two remaining legs — dropping the
connection's Hub subscriptions and writer binding
(:meth:`~punt_lux.domain.hub.hub.Hub.on_disconnect`), and firing its
registered :class:`~punt_lux.domain.hub.departure_sinks.DepartureSinks` entry
(today, only ``inbox.drop_session``) — for one connection or a swept set,
called from *inside* the same lock hold that removed the connection from the
registry. That single hold is what closes the race a naive bolt-on would
introduce: a same-identity reconnect landing between "removed from the
registry" and "the cascade tail ran" would otherwise have its fresh writer
binding wiped out by the stale departure's tail.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.departure_sinks import DepartureSinks

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.domain.hub.departure_sinks import DepartureSink
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.ids import ConnectionId

__all__ = ["DepartureCascade"]

logger = logging.getLogger(__name__)


@final
class DepartureCascade:
    """Sequence the subscriptions/writer/inbox cascade tail for departures."""

    _hub: Hub
    _sinks: DepartureSinks
    __slots__ = ("_hub", "_sinks")

    def __new__(cls, hub: Hub) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        self._sinks = DepartureSinks()
        return self

    def bind_sink(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        """Register ``sink`` as the connection's transport-owned cleanup."""
        self._sinks.bind(connection_id, sink)

    def run(self, connection_id: ConnectionId) -> None:
        """Drop the connection's subscriptions and writer, fire its sink.

        Best-effort per leg: ``connection_id`` has already been irreversibly
        removed from the registry by the time this runs, so a raise here
        must never surface as an externally visible disconnect failure, and
        one leg raising must not skip the other.
        """
        try:
            self._hub.on_disconnect(connection_id)
        except Exception:
            logger.exception(
                "departure cascade on_disconnect failed for connection_id=%s",
                connection_id,
            )
        try:
            self._sinks.fire(connection_id)
        except Exception:
            logger.exception(
                "departure cascade sink failed for connection_id=%s", connection_id
            )

    def run_all(self, connection_ids: Iterable[ConnectionId]) -> None:
        """Run the cascade tail for every connection in a swept set.

        ``run`` is itself best-effort per leg, so no connection's cascade
        failure can abort the rest of a swept set or strand a connection
        outside the registry with a live writer, subscriptions, or inbox
        that no future sweep can ever reach again.
        """
        for connection_id in connection_ids:
            self.run(connection_id)
