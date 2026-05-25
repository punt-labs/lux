"""Per-connection topic registry for Agent Subscribe / Publish."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from punt_lux.domain.ids import ConnectionId, Topic

if TYPE_CHECKING:
    from punt_lux.protocol.messages.observer import ObserverMessage

__all__ = ["Handler", "SubscriptionRegistry"]


# A Handler is the outbound writer for the subscribing connection. The Hub
# typically registers one handler per connection: the wire writer that
# serializes an ObserverMessage and sends it back over that connection.
type Handler = Callable[["ObserverMessage"], None]


class SubscriptionRegistry:
    """Connection-scoped registry mapping topics to subscriber handlers.

    Shape ``dict[ConnectionId, dict[Topic, set[Handler]]]`` — the outer
    key makes cleanup ``O(1)`` against the data structure on disconnect
    and prevents cross-connection leakage by construction. Topic name
    collisions across connections are independent: ``A.work_saved`` and
    ``B.work_saved`` live in separate scopes with separate handler sets.

    Concurrency: ``subscribe`` and ``unsubscribe`` take the lock to
    mutate. ``snapshot_subscribers`` takes the lock only long enough to
    copy the handler set for one ``(connection_id, topic)`` pair —
    callers iterate the snapshot outside the lock so a slow handler
    cannot stall concurrent publishes on other topics.
    """

    _by_connection: dict[ConnectionId, dict[Topic, set[Handler]]]
    _lock: threading.Lock

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_connection = {}
        self._lock = threading.Lock()
        return self

    def subscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        handler: Handler,
    ) -> None:
        """Add ``handler`` to ``(connection_id, topic)``'s subscriber set."""
        with self._lock:
            scope = self._by_connection.setdefault(connection_id, {})
            scope.setdefault(topic, set()).add(handler)

    def unsubscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        handler: Handler,
    ) -> None:
        """Drop ``handler`` from ``(connection_id, topic)``. No-op if absent."""
        with self._lock:
            scope = self._by_connection.get(connection_id)
            if scope is None:
                return
            handlers = scope.get(topic)
            if handlers is None:
                return
            handlers.discard(handler)
            if not handlers:
                del scope[topic]
            if not scope:
                del self._by_connection[connection_id]

    def snapshot_subscribers(
        self,
        connection_id: ConnectionId,
        topic: Topic,
    ) -> tuple[Handler, ...]:
        """Copy the subscriber set under the lock; caller iterates outside it."""
        with self._lock:
            scope = self._by_connection.get(connection_id)
            if scope is None:
                return ()
            handlers = scope.get(topic)
            if handlers is None:
                return ()
            return tuple(handlers)

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Remove every topic and handler the connection owns. Idempotent."""
        with self._lock:
            self._by_connection.pop(connection_id, None)

    def topics_for(self, connection_id: ConnectionId) -> frozenset[Topic]:
        """Return the topics the connection has at least one subscriber on."""
        with self._lock:
            scope = self._by_connection.get(connection_id)
            if scope is None:
                return frozenset()
            return frozenset(scope)
