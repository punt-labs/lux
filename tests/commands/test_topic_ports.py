"""TopicOps -- the Protocol every topic (pub-sub) command implementer satisfies."""

from __future__ import annotations

from punt_lux.commands._topic_ports import TopicOps
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Published, Scope, Subscribed, Unsubscribed
from punt_lux.operations.models.pubsub import PublishRequest, Received


class _Implementer:
    """Satisfies ``TopicOps`` by shape alone -- no explicit inheritance."""

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published:
        del topic, request, scope
        return Published(delivered=0)

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed:
        del scope
        return Subscribed(topic=topic)

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed:
        del scope
        return Unsubscribed(topic=topic)

    def receive(self, *, scope: Scope) -> Received:
        del scope
        return Received(event=None)


def test_a_matching_shape_satisfies_the_protocol_structurally() -> None:
    assert isinstance(_Implementer(), TopicOps)


def test_an_object_missing_every_method_does_not_satisfy_it() -> None:
    assert not isinstance(object(), TopicOps)


def test_receive_takes_only_scope() -> None:
    result = _Implementer().receive(scope=Scope(ConnectionId("c1")))
    assert result == Received(event=None)
