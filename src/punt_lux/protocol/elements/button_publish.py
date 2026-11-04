"""``ButtonPublish`` — a button's declarative "publish this topic on click".

A button may declare that clicking it publishes an application event: a topic
and a static payload template the Hub fans out to that topic's subscribers. The
declaration is a typed element attribute, not a handler-decorator shorthand, so
the element self-validates it (an empty topic is a component-appropriate error)
and it round-trips on the wire as its own field.

The declaration is inert data until a :class:`PublishOnClick` binds its button
to a :class:`PublishSink`: the Hub installs it with the real sink, the agent tier
with a no-op sink, and the Display never runs it locally (its handlers are
wrapped for remote dispatch back to the Hub). It is one more handler in the
button's click bucket, not a replacement for the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, cast, final

if TYPE_CHECKING:
    from punt_lux.domain.event_protocol import Event
    from punt_lux.domain.handlers.publish_sink import PublishSink
    from punt_lux.protocol.elements.button import ButtonElement

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
        # An empty payload is the common, valid case (e.g. music.stop), so it is
        # the default rather than an absence. The value is copied, and its keys
        # enforced to be strings, for both doors: direct and from_wire.
        self = super().__new__(cls)
        self._topic = topic
        self._payload = cls._require_string_keys(payload)
        return self

    @staticmethod
    def _require_string_keys(payload: Mapping[str, object]) -> dict[str, object]:
        """Return a copy of ``payload``, rejecting any non-string key.

        A JSON object and ``__hash__``'s sorted-key tuple both require string
        keys, so a non-string key would make ``to_wire`` non-serializable or a
        mixed-key sort raise.
        """
        entry = cast("Mapping[object, object]", payload)
        for key in entry:
            if not isinstance(key, str):
                raise ButtonPublish._malformed(
                    f"'publish.payload' keys must be strings, got {key!r}"
                )
        return dict(payload)

    @staticmethod
    def _malformed(detail: str) -> TypeError:
        """Return the error for a ``publish`` field that breaks its wire shape."""
        return TypeError(f"button {detail}")

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

        ``publish`` must be a mapping with a string ``topic`` and, when present,
        a string-keyed ``payload`` mapping. An empty topic passes here: the
        element's ``validate`` reports it, so every problem in a tree surfaces
        at once instead of aborting the decode.
        """
        if not isinstance(raw, Mapping):
            raise cls._malformed(
                f"'publish' must be a mapping, got {type(raw).__name__}"
            )
        entry = cast("Mapping[str, object]", raw)
        topic = entry.get("topic")
        if not isinstance(topic, str):
            raise cls._malformed(f"'publish.topic' must be a string, got {topic!r}")
        return cls(topic, cls._payload_from_wire(entry.get("payload")))

    @staticmethod
    def _payload_from_wire(raw: object) -> Mapping[str, object]:
        """Return the payload mapping, defaulting to empty, rejecting a non-mapping.

        Key types are checked by the constructor, shared with direct construction.
        """
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ButtonPublish._malformed(
                f"'publish.payload' must be a mapping, got {type(raw).__name__}"
            )
        return cast("Mapping[str, object]", raw)

    def to_wire(self) -> dict[str, object]:
        """Render as the wire ``publish`` field; an empty payload is omitted."""
        wire: dict[str, object] = {"topic": self._topic}
        if self._payload:
            wire["payload"] = self._payload_copy()
        return wire

    def _payload_copy(self) -> dict[str, object]:
        """Return a mutable copy of the payload for a serializer to own."""
        return dict(self._payload)

    def publish_to(self, sink: PublishSink) -> None:
        """Publish the topic and payload through ``sink``."""
        sink(self._topic, self._payload)

    def topic_error(self) -> str | None:
        """Return a message when the topic is empty, else ``None`` (no error)."""
        if self._topic:
            return None
        return "publish topic must be a non-empty string"

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (ButtonPublish, (self._topic, self._payload_copy()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ButtonPublish):
            return NotImplemented
        return self._topic == other._topic and self._payload == other._payload

    def __hash__(self) -> int:
        return hash((ButtonPublish, self._topic, tuple(sorted(self._payload))))

    def __repr__(self) -> str:
        return f"ButtonPublish(topic={self._topic!r}, payload={self._payload_copy()!r})"


@final
class PublishOnClick:
    """A click handler that publishes its button's current declaration via a sink.

    It holds the button, never a copy of the declaration, so a patch changes what
    the next click publishes. Serializable for the Hub-to-Display wire; on the
    Display the click bucket is wrapped for remote dispatch, so this runs only on
    the Hub. A no-op sink (the agent tier) makes it inert.
    """

    _sink: PublishSink
    _button: ButtonElement
    __slots__ = ("_button", "_sink")

    def __new__(cls, sink: PublishSink, button: ButtonElement) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._button = button
        return self

    def __call__(self, _event: Event) -> None:
        """Publish the button's current declaration; a cleared one publishes nothing."""
        declaration = self._button.publish
        if declaration is not None:
            declaration.publish_to(self._sink)

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (PublishOnClick, (self._sink, self._button))
