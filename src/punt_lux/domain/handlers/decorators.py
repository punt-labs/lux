"""Decorator factories for the declarative handler catalog.

A decorator factory has the shape
``Callable[[Handler[E]], Handler[E]]`` — type-preserving in the event
class so the wrapped handler stays typed end to end. The ``publish``
decorator is the only concrete factory in PR 4; future PRs add
``log``, ``throttle``, and ``confirm_first`` by registering against
the same ``DecoratorRegistry``.

The wire form is a tagged dict (``{"decorator": "publish", "topics":
[...]}``) and the registry resolves the ``decorator`` name to a
typed factory built from the remaining keys.

``PublishSink`` is the structural contract the ``Hub`` will satisfy.
Until then, tests inject any callable that records the
``(topic, payload)`` pairs the decorator emits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, Self, cast, runtime_checkable

from punt_lux.domain.event_protocol import Event, Handler

__all__ = [
    "DecoratorFactory",
    "DecoratorRegistry",
    "PublishDecorator",
    "PublishSink",
]


@runtime_checkable
class PublishSink(Protocol):
    """Structural contract for the ``publish`` decorator's sink.

    The Hub satisfies this; until then, tests pass a recording
    callable. The decorator is the only call site, so the
    surface stays one method.
    """

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        """Publish ``payload`` to ``topic`` in the decorator owner's scope."""
        ...


# A decorator factory wraps an inner ``Handler[E]`` into an outer
# ``Handler[E]``. ``E`` stays free so the chain is type-preserving.
type DecoratorFactory[E: Event] = Callable[[Handler[E]], Handler[E]]


class PublishDecorator:
    """The ``publish`` decorator factory bound to a ``PublishSink``.

    Constructing the decorator captures the sink and the topics; calling
    the decorator wraps an inner ``Handler[E]`` so each invocation runs
    the inner first, then publishes one empty-payload message per topic.
    The empty-payload shape is the PR 4 default; future iterations may
    let the agent describe a payload template.
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
            _PublishWrappedHandler(
                inner=cast("Handler[Event]", inner),
                sink=self._sink,
                topics=self._topics,
            ),
        )


class _PublishWrappedHandler:
    """Serializable handler wrapper that runs ``inner`` then publishes topics.

    Replaces the closure returned by ``PublishDecorator.wrap`` so the
    handler chain survives native serialization across the Hub-to-Display
    wire.
    """

    _inner: Handler[Event]
    _sink: PublishSink
    _topics: tuple[str, ...]

    def __new__(
        cls,
        *,
        inner: Handler[Event],
        sink: PublishSink,
        topics: tuple[str, ...],
    ) -> Self:
        self = super().__new__(cls)
        self._inner = inner
        self._sink = sink
        self._topics = topics
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (
            object.__new__,
            (type(self),),
            {"_inner": self._inner, "_sink": self._sink, "_topics": self._topics},
        )

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, event: Event) -> None:
        self._inner(event)
        payload: Mapping[str, object] = {}
        for topic in self._topics:
            self._sink(topic, payload)


class DecoratorRegistry:
    """Resolves wire decorator specs to typed ``DecoratorFactory`` callables.

    The registry holds a mapping of decorator name to a builder that
    consumes the remaining wire keys and returns a typed factory. The
    decoder walks the wire ``wrap`` list and resolves each entry through
    ``resolve``.
    """

    _sink: PublishSink
    _builders: dict[str, Callable[[Mapping[str, object]], DecoratorFactory[Event]]]

    def __new__(cls, *, sink: PublishSink) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._builders = {}
        self._register_publish()
        return self

    def _register_publish(self) -> None:
        """Wire the ``publish`` decorator into the registry."""

        def _build_publish(
            spec: Mapping[str, object],
        ) -> DecoratorFactory[Event]:
            topics_raw = spec.get("topics")
            if not isinstance(topics_raw, list):
                msg = f"publish decorator requires 'topics' list, got {topics_raw!r}"
                raise ValueError(msg)
            topics: list[str] = []
            for i, item in enumerate(cast("list[object]", topics_raw)):
                if not isinstance(item, str):
                    msg = (
                        f"publish.topics[{i}] must be a string, "
                        f"got {type(item).__name__}"
                    )
                    raise TypeError(msg)
                topics.append(item)
            decorator = PublishDecorator(sink=self._sink, topics=tuple(topics))
            return decorator.wrap

        self._builders["publish"] = _build_publish

    def resolve(self, spec: Mapping[str, object]) -> DecoratorFactory[Event]:
        """Look up ``spec['decorator']`` and build the typed factory."""
        name = spec.get("decorator")
        if not isinstance(name, str) or not name:
            msg = f"decorator spec missing 'decorator' name: {spec!r}"
            raise ValueError(msg)
        builder = self._builders.get(name)
        if builder is None:
            known = sorted(self._builders)
            msg = f"unknown decorator: {name!r} (expected one of {known})"
            raise ValueError(msg)
        return builder(spec)

    @property
    def registered_names(self) -> frozenset[str]:
        """Return the decorator names this registry recognises."""
        return frozenset(self._builders)
