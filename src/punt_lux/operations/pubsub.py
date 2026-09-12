"""PubSubOperations — the Agent Subscribe / Publish surface over the Hub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.ids import Topic
from punt_lux.operations.models import OpError
from punt_lux.operations.models.pubsub import BusEvent, Received
from punt_lux.operations.models.pubsub_acks import Published, Subscribed, Unsubscribed
from punt_lux.operations.reserved_topics import RESERVED_TOPICS

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.operations.models.pubsub import PublishRequest
    from punt_lux.operations.ports import HubPorts
    from punt_lux.operations.scope import Scope

__all__ = ["PubSubOperations"]


@final
class PubSubOperations:
    """Subscribe, unsubscribe, publish, and receive within a caller's scope."""

    _hub: Hub
    _clients: HubClientRegistry
    _ports: HubPorts
    __slots__ = ("_clients", "_hub", "_ports")

    def __new__(cls, hub: Hub, clients: HubClientRegistry, ports: HubPorts) -> Self:
        self = super().__new__(cls)
        self._hub, self._clients, self._ports = hub, clients, ports
        return self

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed | OpError:
        """Register the caller's session for ``topic``; declaration is implicit.

        A reserved (``lux.``) topic is refused before any contact: those topics
        carry Hub-owned events and are not an agent's to subscribe to.
        """
        if RESERVED_TOPICS.covers(topic):
            return RESERVED_TOPICS.rejection(topic)
        self._contact(scope)
        self._hub.subscribe(scope.connection_id, Topic(topic))
        return Subscribed(topic=topic)

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed | OpError:
        """Drop the caller's subscription to ``topic``; a no-op if absent.

        A reserved (``lux.``) topic is refused: an agent can never hold such a
        subscription, so the namespace stays uniformly closed at every verb.
        """
        if RESERVED_TOPICS.covers(topic):
            return RESERVED_TOPICS.rejection(topic)
        self._clients.renew_if_registered(scope.connection_id)
        if self._hub.has_writer(scope.connection_id):
            self._hub.unsubscribe(scope.connection_id, Topic(topic))
        return Unsubscribed(topic=topic)

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published | OpError:
        """Fan the payload out to ``topic``'s in-scope subscribers.

        A reserved (``lux.``) topic is refused before any contact: an agent
        cannot spoof a Hub-owned event onto an inbox by publishing it.
        """
        if RESERVED_TOPICS.covers(topic):
            return RESERVED_TOPICS.rejection(topic)
        self._contact(scope)
        sent = self._hub.publish(scope.connection_id, Topic(topic), request.payload)
        return Published(delivered=sent)

    def receive(self, *, scope: Scope) -> Received:
        """Take the next business event for the caller's session, or none."""
        self._contact(scope)
        message = self._ports.next_event(scope.connection_id, 0.0)
        if message is None:
            return Received(event=None)
        event = BusEvent(topic=message.topic, payload=dict(message.payload))
        return Received(event=event)

    def _contact(self, scope: Scope) -> None:
        """Renew the caller's lease and ensure its writer: authenticated contact."""
        self._clients.renew_if_registered(scope.connection_id)
        self._ports.ensure_writer(scope.connection_id)
