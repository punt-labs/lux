"""``ButtonPublish`` — a button's declarative "publish this topic on click".

A button may declare that clicking it publishes an application event: a topic
and a static payload template the Hub fans out to that topic's subscribers. The
declaration is a typed element attribute, not a handler-decorator shorthand, so
the element self-validates it (an empty topic is a component-appropriate error)
and it round-trips on the wire as its own field.

The declaration is inert data until a :class:`PublishOnClick` binds its button
to a :class:`PublishSink` on the tier that owns publishing — the Hub. The
handler reads the button's current declaration at click time, so a patch changes
what the next click publishes. The Hub installs it with the real sink, the agent
tier with a no-op sink, and the Display never runs it locally (its handlers are
wrapped for remote dispatch back to the Hub). It composes with the button's
other on-click handlers: one more handler in the click bucket, not a replacement.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Self, cast, final

__all__ = ["ButtonPublish"]

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
        # e.g. music.stop), so it is the default rather than an absence. The value
        # is copied so no caller can mutate shared state through it, and its keys
        # are enforced to be strings here — both construction doors, direct and
        # from_wire, pass through this one check.
        self = super().__new__(cls)
        self._topic = topic
        self._payload = cls._require_string_keys(payload)
        return self

    @staticmethod
    def _require_string_keys(payload: Mapping[str, object]) -> dict[str, object]:
        """Return a copy of ``payload``, rejecting any non-string key.

        A JSON object and ``__hash__``'s sorted-key tuple both require string
        keys, so a non-string key would make ``to_wire`` non-serializable or a
        mixed-key sort raise. The check lives on the constructor so a directly
        built instance is held to the same invariant ``from_wire`` enforces at
        the wire boundary — one validation, both doors.
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

        Enforces structure at the boundary: ``publish`` must be a mapping with a
        string ``topic`` and, when present, a string-keyed ``payload`` mapping. An
        empty topic passes here — it is a *semantic* fault the element's
        ``validate`` reports so every problem in a tree surfaces at once, not a
        structural one that aborts the decode.
        """
        entry = cls._mapping_from_wire(raw, "publish")
        return cls(
            cls._topic_from_wire(entry.get("topic")),
            cls._payload_from_wire(entry.get("payload")),
        )

    @staticmethod
    def _topic_from_wire(raw: object) -> str:
        """Return the wire ``topic``, rejecting a non-string."""
        if not isinstance(raw, str):
            raise ButtonPublish._malformed(
                f"'publish.topic' must be a string, got {raw!r}"
            )
        return raw

    @staticmethod
    def _mapping_from_wire(raw: object, field: str) -> Mapping[str, object]:
        """Return ``raw`` as a mapping, rejecting any other shape of ``field``."""
        if not isinstance(raw, Mapping):
            raise ButtonPublish._malformed(
                f"'{field}' must be a mapping, got {type(raw).__name__}"
            )
        return cast("Mapping[str, object]", raw)

    @staticmethod
    def _payload_from_wire(raw: object) -> Mapping[str, object]:
        """Return the payload mapping, defaulting to empty, rejecting a non-mapping.

        Only the wire shape (present and a mapping) is checked here; the
        key-is-string invariant is enforced in the constructor, so both the wire
        door and direct construction share it.
        """
        if raw is None:
            return {}
        return ButtonPublish._mapping_from_wire(raw, "publish.payload")

    def to_wire(self) -> dict[str, object]:
        """Render as the wire ``publish`` field; an empty payload is omitted."""
        wire: dict[str, object] = {"topic": self._topic}
        if self._payload:
            wire["payload"] = self._payload_copy()
        return wire

    def _payload_copy(self) -> dict[str, object]:
        """Return a mutable copy of the payload for a serializer to own."""
        return dict(self._payload)

    def topic_error(self) -> str | None:
        """Return a message when the topic is empty, else ``None``.

        ``None`` is the documented "no error" contract the element's ``validate``
        folds into its error tuple — the one place the empty-topic rule lives.
        """
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
