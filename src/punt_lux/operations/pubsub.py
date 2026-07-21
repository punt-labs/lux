"""PubSubOperations — the Agent Subscribe / Publish surface over the Hub.

These operations register a session's writer, fan payloads out to a topic's
in-scope subscribers, and drain the session inbox. They are Hub-owned and
scoped by connection; the Hub and the session inbox are given at construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.ids import Topic
from punt_lux.operations.models.pubsub import BusEvent, Received
from punt_lux.operations.models.pubsub_acks import Published, Subscribed, Unsubscribed

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.operations.models.pubsub import PublishRequest
    from punt_lux.operations.ports import EnsureWriter, NextEvent
    from punt_lux.operations.scope import Scope

__all__ = ["PubSubOperations"]


@final
class PubSubOperations:
    """Subscribe, unsubscribe, publish, and receive within a caller's scope."""

    _hub: Hub
    _ensure_writer: EnsureWriter
    _next_event: NextEvent
    __slots__ = ("_ensure_writer", "_hub", "_next_event")

    def __new__(
        cls, hub: Hub, ensure_writer: EnsureWriter, next_event: NextEvent
    ) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        self._ensure_writer = ensure_writer
        self._next_event = next_event
        return self

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed:
        """Register the caller's session for ``topic``; declaration is implicit."""
        self._ensure_writer(scope.connection_id)
        self._hub.subscribe(scope.connection_id, Topic(topic))
        return Subscribed(topic=topic)

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed:
        """Drop the caller's subscription to ``topic``; a no-op if absent."""
        if not self._hub.has_writer(scope.connection_id):
            return Unsubscribed(topic=topic)
        self._hub.unsubscribe(scope.connection_id, Topic(topic))
        return Unsubscribed(topic=topic)

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published:
        """Fan the payload out to ``topic``'s in-scope subscribers."""
        self._ensure_writer(scope.connection_id)
        delivered = self._hub.publish(
            scope.connection_id, Topic(topic), request.payload
        )
        return Published(delivered=delivered)

    def receive(self, *, scope: Scope) -> Received:
        """Take the next business event for the caller's session, or none."""
        self._ensure_writer(scope.connection_id)
        message = self._next_event(scope.connection_id, 0.0)
        if message is None:
            return Received(event=None)
        return Received(
            event=BusEvent(topic=message.topic, payload=dict(message.payload))
        )
