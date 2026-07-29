"""``ButtonPublish`` — a button's declarative "publish this topic on click".

A button may declare that clicking it publishes an application event: a topic
and a static payload template the Hub fans out to that topic's subscribers. The
declaration is a typed element attribute, not a handler-decorator shorthand, so
the element self-validates it (an empty topic is a component-appropriate error)
and it round-trips on the wire as its own field.

The declaration is inert data until it is bound to a :class:`PublishSink` on the
tier that owns publishing — the Hub. :meth:`ButtonPublish.handler_for` returns
the serializable click handler that fires the publish; the Hub tier installs it
with the real sink, the agent tier with a no-op sink, and the Display never runs
it locally (its handlers are wrapped for remote dispatch back to the Hub). This
composes with the button's existing on-click handlers: publish is one more
handler in the click bucket, added beside the others, not a replacement.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.domain.interaction import ButtonClicked

__all__ = ["ButtonPublish", "PublishOnClick"]

# The immutable default payload — a topic published with no arguments.
_EMPTY: Mapping[str, object] = MappingProxyType({})


@final
class ButtonPublish:
    """A topic and a static payload a button publishes when clicked."""

    _topic: str
    _payload: Mapping[str, object]
    __slots__ = ("_payload", "_topic")

    def __new__(cls, topic: str, payload: Mapping[str, object] = _EMPTY) -> Self:
        # An empty payload is the common, valid case (a topic with no arguments,
        # e.g. music.stop), so it is the default rather than an absence. The
        # default is an immutable empty mapping and the value is copied, so no
        # caller can mutate shared state through it.
        self = super().__new__(cls)
        self._topic = topic
        self._payload = dict(payload)
        return self

    @property
    def topic(self) -> str:
        """Return the topic this button publishes to on click."""
        return self._topic

    @property
    def payload(self) -> Mapping[str, object]:
        """Return the static payload published with each click."""
        return self._payload

    @classmethod
    def from_wire(cls, raw: object) -> Self:
        """Build from the wire ``publish`` field, rejecting a malformed shape.

        Enforces structure at the boundary: ``publish`` must be a mapping with a
        string ``topic`` and, when present, a string-keyed ``payload`` mapping. An
        empty topic passes here — it is a *semantic* fault the element's
        ``validate`` reports so every problem in a tree surfaces at once, not a
        structural one that aborts the decode.
        """
        if not isinstance(raw, Mapping):
            msg = f"button 'publish' must be a mapping, got {type(raw).__name__}"
            raise TypeError(msg)
        entry = cast("Mapping[str, object]", raw)
        topic = entry.get("topic")
        if not isinstance(topic, str):
            msg = f"button 'publish.topic' must be a string, got {topic!r}"
            raise TypeError(msg)
        return cls(topic, cls._payload_from_wire(entry.get("payload")))

    @staticmethod
    def _payload_from_wire(raw: object) -> Mapping[str, object]:
        """Return the payload mapping, defaulting to empty, rejecting a non-mapping."""
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            msg = (
                f"button 'publish.payload' must be a mapping, got {type(raw).__name__}"
            )
            raise TypeError(msg)
        entry = cast("Mapping[object, object]", raw)
        for key in entry:
            if not isinstance(key, str):
                msg = f"button 'publish.payload' keys must be strings, got {key!r}"
                raise TypeError(msg)
        return cast("Mapping[str, object]", dict(entry))

    def to_wire(self) -> dict[str, object]:
        """Render as the wire ``publish`` field; an empty payload is omitted."""
        wire: dict[str, object] = {"topic": self._topic}
        if self._payload:
            wire["payload"] = dict(self._payload)
        return wire

    def topic_error(self) -> str | None:
        """Return a message when the topic is empty, else ``None``.

        ``None`` is the documented "no error" contract the element's ``validate``
        folds into its error tuple — the one place the empty-topic rule lives.
        """
        if self._topic:
            return None
        return "publish topic must be a non-empty string"

    def handler_for(self, sink: PublishSink) -> Handler[ButtonClicked]:
        """Return the serializable click handler that publishes through ``sink``."""
        return cast("Handler[ButtonClicked]", PublishOnClick(sink, self))

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (ButtonPublish, (self._topic, dict(self._payload)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ButtonPublish):
            return NotImplemented
        return self._topic == other._topic and self._payload == other._payload

    def __hash__(self) -> int:
        return hash((ButtonPublish, self._topic, tuple(sorted(self._payload))))

    def __repr__(self) -> str:
        return f"ButtonPublish(topic={self._topic!r}, payload={dict(self._payload)!r})"


@final
class PublishOnClick:
    """A click handler that publishes a button's declared topic through a sink.

    Serializable so it survives the Hub-to-Display native-pickle wire: on the
    Display its whole click bucket is wrapped for remote dispatch, so this never
    runs there; on the Hub it fires the real publish. A no-op sink (the agent
    tier) makes it inert without a separate branch.
    """

    _sink: PublishSink
    _declaration: ButtonPublish
    __slots__ = ("_declaration", "_sink")

    def __new__(cls, sink: PublishSink, declaration: ButtonPublish) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._declaration = declaration
        return self

    def __call__(self, _event: Event) -> None:
        """Publish the declared topic and payload; the click event carries nothing."""
        self._sink(self._declaration.topic, self._declaration.payload)

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (PublishOnClick, (self._sink, self._declaration))
