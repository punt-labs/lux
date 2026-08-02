"""Decorator factories for the declarative handler catalog.

A decorator factory has the shape
``Callable[[Handler[E]], Handler[E]]`` — type-preserving in the event
class so the wrapped handler stays typed end to end. ``publish`` is the
only concrete factory; ``log``, ``throttle``, and ``confirm_first`` would
be written the same way and registered beside it in
``decorator_registry``, which owns the wire lookup.

What a ``publish`` sends is the event's own data — its kind, the scene and
element it happened on, and its payload fields (a row selection's ``row_ids``
and ``anchor``, an input's ``value``). The event renders that mapping itself
(``WireEvent.to_payload``), so this module holds no per-kind knowledge.

The sink the decorator publishes through is the ``PublishSink`` beside it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Self, cast

from punt_lux.domain.event_protocol import Event, Handler
from punt_lux.domain.handlers.publish_sink import PublishSink
from punt_lux.domain.wire_event import WireEvent

__all__ = [
    "DecoratorFactory",
    "PublishDecorator",
]


# A decorator factory wraps an inner ``Handler[E]`` into an outer
# ``Handler[E]``. ``E`` stays free so the chain is type-preserving.
type DecoratorFactory[E: Event] = Callable[[Handler[E]], Handler[E]]


class PublishDecorator:
    """The ``publish`` decorator factory bound to a ``PublishSink``.

    Constructing the decorator captures the sink and the topics; calling
    the decorator wraps an inner ``Handler[E]`` so each invocation runs
    the inner first, then publishes the event's own payload once per topic.
    The payload is whatever the event's ``to_payload`` renders — the same
    mapping for every topic in the list, since one interaction happened.
    """

    _sink: PublishSink
    _topics: tuple[str, ...]

    def __new__(cls, *, sink: PublishSink, topics: tuple[str, ...]) -> Self:
        if not topics:
            msg = "publish decorator requires at least one topic"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._sink = sink
        self._topics = topics
        return self

    @property
    def topics(self) -> tuple[str, ...]:
        """Return the topics this decorator fires on each invocation."""
        return self._topics

    def wrap[E: Event](self, inner: Handler[E]) -> Handler[E]:
        """Return a handler that runs ``inner`` then publishes the topics."""
        return cast(
            "Handler[E]",
            _PublishWrappedHandler(inner=cast("Handler[Event]", inner), decorator=self),
        )

    def publish(self, event: WireEvent) -> None:
        """Send what ``event`` renders to every topic through the sink.

        The event composes its own payload, so a new event kind publishes
        correctly without this method learning anything about it. One
        interaction happened, so every topic receives the same mapping.
        """
        payload = event.to_payload()
        for topic in self._topics:
            self._sink(topic, payload)

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization — the wrapped handler holds one of these."""
        return (
            object.__new__,
            (type(self),),
            {"_sink": self._sink, "_topics": self._topics},
        )


class _PublishWrappedHandler:
    """Serializable handler wrapper that runs ``inner`` then asks for the publish.

    Replaces the closure returned by ``PublishDecorator.wrap`` so the
    handler chain survives native serialization across the Hub-to-Display
    wire. Every event on the remote-dispatch path is a ``WireEvent``; the
    ``publish`` decorator is only ever wired onto those buckets.
    """

    _inner: Handler[Event]
    _decorator: PublishDecorator

    def __new__(cls, *, inner: Handler[Event], decorator: PublishDecorator) -> Self:
        self = super().__new__(cls)
        self._inner = inner
        self._decorator = decorator
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (
            object.__new__,
            (type(self),),
            {"_inner": self._inner, "_decorator": self._decorator},
        )

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, event: WireEvent) -> None:
        """Run the inner handler, then let the decorator publish the event."""
        self._inner(event)
        self._decorator.publish(event)
