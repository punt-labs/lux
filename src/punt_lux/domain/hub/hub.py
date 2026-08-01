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

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.domain.hub.subscription_registry import Handler, SubscriptionRegistry
from punt_lux.domain.hub.writer_registry import WriterRegistry
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Hub", "hub"]

logger = logging.getLogger(__name__)


class Hub:
    """Connection-scoped pub-sub coordinator.

    Holds two per-connection registries and does the coordinating between
    them: ``_subscriptions`` (topics → handlers) and ``_writers``
    (connection → outbound wire writer). The writer registry is
    populated when a connection comes online — the transport adapter
    calls ``register_writer`` before any tool call on that connection
    runs ``subscribe`` or ``publish``.

    Publish fan-out is snapshot-then-iterate: the registry copies the
    subscriber set under a short lock, then the Hub iterates the
    snapshot outside the lock so a slow handler cannot stall concurrent
    publishes on other topics.
    """

    _subscriptions: SubscriptionRegistry
    _writers: WriterRegistry

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._subscriptions = SubscriptionRegistry()
        self._writers = WriterRegistry()
        return self

    def register_writer(
        self,
        connection_id: ConnectionId,
        writer: Handler,
    ) -> None:
        """Bind a connection's outbound writer. Idempotent overwrites."""
        self._writers.bind(connection_id, writer)

    def release_writer(self, connection_id: ConnectionId, writer: Handler) -> None:
        """Drop what ``writer`` installed on this connection, and only that.

        The counterpart of :meth:`register_writer`, for a leg whose connection id
        it shares with the sessions that precede and follow it. Both removals are
        by the writer's own identity: its subscriptions go from every topic it
        joined, and the binding goes only while it is still the connection's. A
        session that was superseded while suspended therefore takes its own state
        and leaves its successor's — the ownership rule the listener slot already
        enforces, applied to the state the Hub holds.
        """
        self._subscriptions.drop_handler(connection_id, writer)
        self._writers.release(connection_id, writer)

    def has_writer(self, connection_id: ConnectionId) -> bool:
        """Return whether a writer is registered for ``connection_id``."""
        return self._writers.has(connection_id)

    def subscribe(self, connection_id: ConnectionId, topic: Topic) -> None:
        """Register the caller's connection for ``topic``.

        Declaration is implicit — the first subscribe (or publish) on a
        topic name within a connection's scope declares it. Raises
        ``KeyError`` if no writer has been registered for the
        connection: the registration would have no recipient.
        """
        handler = self._writers.writer_for(connection_id)
        self._subscriptions.subscribe(connection_id, topic, handler)

    def unsubscribe(self, connection_id: ConnectionId, topic: Topic) -> None:
        """Drop the caller's subscription to ``topic``. No-op if absent."""
        handler = self._writers.writer_for(connection_id)
        self._subscriptions.unsubscribe(connection_id, topic, handler)

    def publish(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        payload: Mapping[str, object],
    ) -> int:
        """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

        Returns the number of subscribers that actually received the
        message. Snapshot-then-iterate: the registry takes the lock just
        long enough to copy the subscriber set, releases, then the Hub
        iterates outside the lock to invoke each handler. A handler that
        raises is logged and skipped; one bad subscriber must not abort
        fan-out to the remaining well-behaved subscribers.
        """
        message = ObserverMessage(topic=topic, payload=payload)
        subscribers = self._subscriptions.snapshot_subscribers(connection_id, topic)
        delivered = 0
        for handler in subscribers:
            try:
                handler(message)
            except Exception:
                logger.exception(
                    "subscriber raised handling publish "
                    "(connection=%s, topic=%s); continuing fan-out",
                    connection_id,
                    topic,
                )
                continue
            delivered += 1
        return delivered

    def on_disconnect(self, connection_id: ConnectionId) -> None:
        """Cascade cleanup: drop all subscriptions and the writer binding.

        Connection-scoped: the whole connection has gone, so everything under its
        id goes. A leg that shares its connection id with a successor must use
        :meth:`release_writer` instead, which removes only its own.
        """
        self._subscriptions.drop_connection(connection_id)
        self._writers.drop(connection_id)

    def topics_for(self, connection_id: ConnectionId) -> frozenset[Topic]:
        """Return the connection's currently subscribed topics."""
        return self._subscriptions.topics_for(connection_id)


# Module-level singleton — the production Hub. Tests construct their own
# Hub() to keep state isolated.
hub = Hub()
