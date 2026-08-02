"""PublishSource — how a scenario's target announces its business event.

A scenario declares one ``PublishSource``. It names the ``topic`` the
agent subscribes and the payload I3 asserts the subscriber received, and
it knows how to install its half of the loop onto the target element:

- ``WirePublish`` — the publish is declared in the target's wire dict
  (a button's ``publish`` sugar or an explicit ``handlers`` entry),
  decoded through the real ``PublishDecorator`` → ``HubPublishSink``
  chain. The payload is the interaction's own: its kind, the scene and
  element it landed on, and the event's fields. ``install`` is a no-op —
  the wire dict already carries the pub-sub half.
- ``PayloadPublish`` — the publish comes from an agent-wired Hub-side
  ``PublishingHandler`` announcing a payload of the *app's* own design
  (a ticket id, an album id) rather than the interaction's, straight
  through ``HubPublishSink``. ``install`` registers it on the target's
  interaction bucket.

The two are the two real shapes an app publishes in: "tell me what the
user did" and "tell me what this button means". Keeping both as a
Protocol family (structural typing, no base class) is what makes a new
interactive kind cheap: pick the mechanism that fits and the agent
installs it uniformly.

``WirePublish``'s named constructors spell the payload contract per event
kind — a second, independent statement of what ``WireEvent.to_payload``
renders, so a drift in either shows up here rather than agreeing with
itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.hub_factory import HubPublishSink
from punt_lux.domain.ids import ConnectionId

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

    def payload_for(self, *, scene_id: str, element_id: str) -> Mapping[str, object]:
        """Return the payload I3 asserts, for the scenario's scene and target."""
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


@final
class WirePublish:
    """Publish via the target's wire declaration — the interaction's own payload.

    ``install`` is a no-op because the wire dict already carries the
    publish declaration (a button's ``publish`` sugar or an explicit
    ``handlers`` entry); the real decoder wires the ``PublishDecorator``
    through ``HubPublishSink`` when the agent ``show``s the surface.

    One named constructor per event kind, each stating what that kind
    publishes beyond its identity: a click and a modal close carry nothing
    more, a value input carries its ``value``, a tab bar its ``tab_id``, a
    header its ``open`` state, a table its ``row_ids`` and ``anchor``.
    """

    _topic: str
    _kind: str
    _fields: Mapping[str, object]
    __slots__ = ("_fields", "_kind", "_topic")

    def __new__(cls, topic: str, *, kind: str, fields: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._topic = topic
        self._kind = kind
        self._fields = fields
        return self

    @classmethod
    def click(cls, topic: str) -> Self:
        """A ``button_clicked`` publish — the click carries no data of its own."""
        return cls(topic, kind="button_clicked", fields={})

    @classmethod
    def value(cls, topic: str, *, value: object) -> Self:
        """A ``value_changed`` publish carrying the input's committed ``value``."""
        return cls(topic, kind="value_changed", fields={"value": value})

    @classmethod
    def tab(cls, topic: str, *, tab_id: str) -> Self:
        """A ``tab_changed`` publish carrying the newly-active ``tab_id``."""
        return cls(topic, kind="tab_changed", fields={"tab_id": tab_id})

    @classmethod
    def header(cls, topic: str, *, open_: bool) -> Self:
        """A ``header_toggled`` publish carrying the header's new ``open`` state."""
        return cls(topic, kind="header_toggled", fields={"open": open_})

    @classmethod
    def modal_close(cls, topic: str) -> Self:
        """A ``modal_closed`` publish — the dismissal carries no data of its own."""
        return cls(topic, kind="modal_closed", fields={})

    @classmethod
    def rows(cls, topic: str, *, row_ids: list[str], anchor: str) -> Self:
        """A ``row_selection_changed`` publish carrying the selection and anchor."""
        return cls(
            topic,
            kind="row_selection_changed",
            fields={"row_ids": row_ids, "anchor": anchor},
        )

    @property
    def topic(self) -> str:
        """Return the wire-declared topic."""
        return self._topic

    def payload_for(self, *, scene_id: str, element_id: str) -> Mapping[str, object]:
        """Return the event's payload: identity from the scenario, then the fields."""
        return {
            "kind": self._kind,
            "scene_id": scene_id,
            "element_id": element_id,
            **self._fields,
        }

    def install(
        self,
        target: AbcElement,
        *,
        connection_id: str,
        event_type: type[Event],
    ) -> None:
        """No-op: the wire ``publish`` declaration already installed this half."""
        _ = (target, connection_id, event_type)


@final
class PayloadPublish:
    """Publish an app-authored payload via an agent-wired Hub-side handler.

    ``install`` registers a ``PublishingHandler`` on the target's
    interaction bucket. The handler holds a ``HubPublishSink`` bound to the
    owning connection, so on fire it reaches ``hub.publish`` with a payload
    the app chose — a ticket id, not a description of the gesture. This is
    the other half of the publish story from ``WirePublish``: the same sink,
    a payload the interaction knows nothing about.
    """

    _topic: str
    _payload: Mapping[str, object]
    __slots__ = ("_payload", "_topic")

    def __new__(cls, *, topic: str, payload: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._topic = topic
        self._payload = payload
        return self

    @property
    def topic(self) -> str:
        """Return the handler-published topic."""
        return self._topic

    def payload_for(self, *, scene_id: str, element_id: str) -> Mapping[str, object]:
        """Return the app-authored payload; it does not describe the interaction."""
        _ = (scene_id, element_id)
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
