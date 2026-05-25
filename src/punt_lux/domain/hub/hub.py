"""Hub — cross-process pub-sub surface for agents and applets.

The Hub owns the per-connection ``SubscriptionRegistry`` and a
per-connection writer registry. ``subscribe`` / ``unsubscribe`` register
the caller-connection's own outbound writer against a topic; ``publish``
fans an ``ObserverMessage`` payload out to that connection's
subscribers. Every operation is scoped to ``connection_id`` — a
connection cannot see, touch, or publish into another connection's
topics.

This is the Agent Subscribe / Publish subsystem; it is distinct from
the intra-Hub Element Observer pattern that propagates property changes
to parent composites. The two share no machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.subscription_registry import Handler, SubscriptionRegistry
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Hub", "hub"]


class Hub:
    """Connection-scoped pub-sub coordinator.

    Holds two per-connection registries: ``_subscriptions`` (topics →
    handlers) and ``_writers`` (connection → outbound wire writer). The
    writer registry is populated when a connection comes online — the
    transport adapter calls ``register_writer`` before any tool call on
    that connection runs ``subscribe`` or ``publish``.

    Publish fan-out is snapshot-then-iterate: the registry copies the
    subscriber set under a short lock, then the Hub iterates the
    snapshot outside the lock so a slow handler cannot stall concurrent
    publishes on other topics.
    """

    _subscriptions: SubscriptionRegistry
    _writers: dict[ConnectionId, Handler]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._subscriptions = SubscriptionRegistry()
        self._writers = {}
        return self

    def register_writer(
        self,
        connection_id: ConnectionId,
        writer: Handler,
    ) -> None:
        """Bind a connection's outbound writer. Idempotent overwrites."""
        self._writers[connection_id] = writer

    def unregister_writer(self, connection_id: ConnectionId) -> None:
        """Drop the connection's writer binding. No-op if absent."""
        self._writers.pop(connection_id, None)

    def has_writer(self, connection_id: ConnectionId) -> bool:
        """Return whether a writer is registered for ``connection_id``."""
        return connection_id in self._writers

    def subscribe(self, connection_id: ConnectionId, topic: Topic) -> None:
        """Register the caller's connection for ``topic``.

        Declaration is implicit — the first subscribe (or publish) on a
        topic name within a connection's scope declares it. Raises
        ``KeyError`` if no writer has been registered for the
        connection: the registration would have no recipient.
        """
        handler = self._writer_for(connection_id)
        self._subscriptions.subscribe(connection_id, topic, handler)

    def unsubscribe(self, connection_id: ConnectionId, topic: Topic) -> None:
        """Drop the caller's subscription to ``topic``. No-op if absent."""
        handler = self._writer_for(connection_id)
        self._subscriptions.unsubscribe(connection_id, topic, handler)

    def publish(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        payload: Mapping[str, object],
    ) -> int:
        """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

        Returns the number of subscribers that received the message.
        Snapshot-then-iterate: the registry takes the lock just long
        enough to copy the subscriber set, releases, then the Hub
        iterates outside the lock to invoke each handler.
        """
        message = ObserverMessage(topic=topic, payload=payload)
        subscribers = self._subscriptions.snapshot_subscribers(connection_id, topic)
        for handler in subscribers:
            handler(message)
        return len(subscribers)

    def on_disconnect(self, connection_id: ConnectionId) -> None:
        """Cascade cleanup: drop all subscriptions and the writer binding."""
        self._subscriptions.drop_connection(connection_id)
        self.unregister_writer(connection_id)

    def topics_for(self, connection_id: ConnectionId) -> frozenset[Topic]:
        """Return the connection's currently subscribed topics."""
        return self._subscriptions.topics_for(connection_id)

    def _writer_for(self, connection_id: ConnectionId) -> Handler:
        """Resolve the connection's outbound writer; raise if unbound."""
        writer = self._writers.get(connection_id)
        if writer is None:
            msg = f"no writer registered for connection {connection_id!r}"
            raise KeyError(msg)
        return writer


# Module-level singleton — the production Hub. Tests construct their own
# Hub() to keep state isolated.
hub = Hub()
