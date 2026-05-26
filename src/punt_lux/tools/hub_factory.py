"""Hub-bound :class:`JsonElementFactory` for in-Hub wire decode.

Elements decoded inside luxd live inside the Hub — their ``publish``
decorators must reach ``Hub.publish(connection_id, topic, payload)`` so
fan-out lands on the right session's subscribers. The agent-side
factory wires :class:`NoOpAgentSideSink`, which swallows every publish;
that's correct on the agent (no Hub), wrong in luxd (the Hub IS the
destination).

:func:`hub_element_factory` returns a fresh :class:`JsonElementFactory`
per call, bound to the supplied ``connection_id``. ``show()`` builds
one factory per tool invocation so the publish sink stays scoped to
the calling session: a click on a Button installed in HubDisplay by
session A publishes to session A's topics, never to session B's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.hub import hub
from punt_lux.domain.ids import Topic
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import build_element_codec
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubPublishSink", "hub_element_factory"]


class HubPublishSink:
    """Connection-scoped :class:`PublishSink` adapter onto :class:`Hub`.

    Captures the calling session's ``ConnectionId`` so every publish a
    decoded Element fires inside the Hub routes to ``Hub.publish``
    against that connection's scope. Satisfies the structural
    ``PublishSink`` Protocol without inheriting from it; the protocol
    lives in ``domain.handlers`` (inner layer) and this adapter lives
    in ``tools`` (presentation/Hub adapter).
    """

    __slots__ = ("_connection_id",)

    _connection_id: ConnectionId

    def __new__(cls, connection_id: ConnectionId) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        """Publish ``payload`` to ``topic`` in the bound connection's scope."""
        hub.publish(self._connection_id, Topic(topic), payload)

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (HubPublishSink, (self._connection_id,))


def _no_op_emit(_msg: object) -> None:
    """Sentinel emit channel for Hub-side decode — Null Object."""


def hub_element_factory(connection_id: ConnectionId) -> JsonElementFactory:
    """Return a fresh Hub-bound :class:`JsonElementFactory` for ``connection_id``.

    The decoded elements' ``publish`` decorators fire through
    :class:`HubPublishSink` directly into ``hub.publish`` against the
    caller's session — the correct destination for elements that live
    inside the Hub mirror. Use this anywhere a luxd-side path decodes
    wire dicts that will land in :class:`HubDisplay`.
    """
    return JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=_no_op_emit,
        publish_sink=cast("Any", HubPublishSink(connection_id)),
        codec=build_element_codec(),
    )
