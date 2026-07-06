"""PublishSource — how a scenario's target announces its business event.

A scenario declares one ``PublishSource``. It names the ``topic`` the
agent subscribes and the ``payload`` I3 asserts the subscriber received,
and it knows how to install its half of the loop onto the target element:

- ``WirePublish`` — the publish is declared in the target's wire dict
  (a button's ``publish`` sugar or a checkbox's explicit ``handlers``
  entry), decoded through the real ``PublishDecorator`` → ``HubPublishSink``
  chain. Payload is always empty (the PR-4 decorator default), so
  ``install`` is a no-op: the wire dict already carries the pub-sub half.
- ``PayloadPublish`` — the publish comes from an agent-wired Hub-side
  ``PublishingHandler`` that announces a **non-empty** payload directly
  through ``HubPublishSink``. ``install`` registers it on the target's
  interaction bucket so I3's payload assertion has teeth.

Keeping both as a Protocol family (structural typing, no base class) is
what makes a new interactive kind cheap: pick the mechanism that fits and
the agent installs it uniformly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from punt_lux.domain.ids import ConnectionId
from punt_lux.tools.hub_factory import HubPublishSink

from .target_handlers import PublishingHandler

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.domain.event_protocol import Event

__all__ = ["PayloadPublish", "PublishSource", "WirePublish"]


@runtime_checkable
class PublishSource(Protocol):
    """The business-event announcement a scenario's target performs."""

    @property
    def topic(self) -> str:
        """Return the topic the agent subscribes and I3 asserts."""
        ...

    @property
    def payload(self) -> Mapping[str, object]:
        """Return the payload I3 asserts the subscriber received."""
        ...

    def install(
        self,
        target: AbcElement,
        *,
        connection_id: str,
        event_type: type[Event],
    ) -> None:
        """Install this source's Hub-side publish half onto ``target``."""
        ...


class WirePublish:
    """Publish via the target's wire declaration — empty payload.

    ``install`` is a no-op because the wire dict already carries the
    publish declaration (a button's ``publish`` sugar or a checkbox's
    ``handlers`` entry); the real decoder wires the ``PublishDecorator``
    through ``HubPublishSink`` when the agent ``show``s the surface.
    """

    _topic: str

    def __new__(cls, topic: str) -> Self:
        self = super().__new__(cls)
        self._topic = topic
        return self

    @property
    def topic(self) -> str:
        """Return the wire-sugar topic."""
        return self._topic

    @property
    def payload(self) -> Mapping[str, object]:
        """Return the empty payload the ``publish`` decorator always fires."""
        return {}

    def install(
        self,
        target: AbcElement,
        *,
        connection_id: str,
        event_type: type[Event],
    ) -> None:
        """No-op: the wire ``publish`` sugar already installed the pub-sub half."""
        _ = (target, connection_id, event_type)


class PayloadPublish:
    """Publish a non-empty payload via an agent-wired Hub-side handler.

    ``install`` registers a ``PublishingHandler`` on the target's
    interaction bucket. The handler holds a ``HubPublishSink`` bound to the
    owning connection, so on fire it reaches ``hub.publish`` with the
    non-empty payload — the mechanism the wire sugar cannot provide.
    """

    _topic: str
    _payload: Mapping[str, object]

    def __new__(cls, *, topic: str, payload: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._topic = topic
        self._payload = payload
        return self

    @property
    def topic(self) -> str:
        """Return the handler-published topic."""
        return self._topic

    @property
    def payload(self) -> Mapping[str, object]:
        """Return the non-empty payload the handler publishes."""
        return self._payload

    def install(
        self,
        target: AbcElement,
        *,
        connection_id: str,
        event_type: type[Event],
    ) -> None:
        """Wire a ``PublishingHandler`` onto ``target``'s interaction bucket."""
        sink = HubPublishSink(ConnectionId(connection_id))
        target.add_handler(
            event_type,
            PublishingHandler(sink=sink, topic=self._topic, payload=self._payload),
        )
