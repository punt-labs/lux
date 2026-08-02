"""The registry that turns a wire decorator spec into a typed factory.

An agent writes each decorator as a tagged dict — ``{"decorator": "publish",
"topics": [...]}``. ``DecoratorRegistry`` resolves the ``decorator`` name and
hands the remaining keys to the class that understands them: ``PublishSpec``
reads the topic list, says what is wrong with a malformed one, and builds the
bound ``PublishDecorator``. A second decorator (``log``, ``throttle``) arrives
as one more spec class registered beside it, not as another branch here.

Kept apart from ``decorators`` so that module holds the decorator itself and
this one holds the wire lookup — the split the ``protocol``/``domain`` boundary
already draws between shapes and behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Self, cast, final

from punt_lux.domain.handlers.decorators import DecoratorFactory, PublishDecorator
from punt_lux.domain.handlers.publish_sink import PublishSink
from punt_lux.domain.wire_event import WireEvent

__all__ = ["DecoratorRegistry", "PublishSpec"]

# A builder consumes one wire decorator spec and returns its ``WireEvent`` factory.
type DecoratorBuilder = Callable[[Mapping[str, object]], DecoratorFactory[WireEvent]]


@final
class PublishSpec:
    """The ``publish`` decorator's wire spec — its validated topic list."""

    _topics: tuple[str, ...]
    __slots__ = ("_topics",)

    def __new__(cls, topics: tuple[str, ...]) -> Self:
        self = super().__new__(cls)
        self._topics = topics
        return self

    @classmethod
    def from_wire(cls, spec: Mapping[str, object]) -> Self:
        """Read ``spec['topics']``, naming the first entry that is not a string."""
        topics_raw = spec.get("topics")
        if not isinstance(topics_raw, list):
            msg = f"publish decorator requires 'topics' list, got {topics_raw!r}"
            raise ValueError(msg)
        return cls(tuple(cls._each_topic(cast("list[object]", topics_raw))))

    @staticmethod
    def _each_topic(topics_raw: list[object]) -> list[str]:
        """Return the topics as strings, rejecting any entry that is not one."""
        topics: list[str] = []
        for i, item in enumerate(topics_raw):
            if not isinstance(item, str):
                msg = f"publish.topics[{i}] must be a string, got {type(item).__name__}"
                raise TypeError(msg)
            topics.append(item)
        return topics

    @property
    def topics(self) -> tuple[str, ...]:
        """Return the topics this spec publishes to."""
        return self._topics

    def factory_for(self, sink: PublishSink) -> DecoratorFactory[WireEvent]:
        """Return the typed decorator factory bound to ``sink``."""
        return PublishDecorator(sink=sink, topics=self._topics).wrap


class DecoratorRegistry:
    """Resolves wire decorator specs to typed ``DecoratorFactory`` callables.

    The registry holds a mapping of decorator name to a builder that
    consumes the wire spec and returns a typed factory. The decoder walks
    the wire ``wrap`` list and resolves each entry through ``resolve``.
    """

    _sink: PublishSink
    _builders: dict[str, DecoratorBuilder]

    def __new__(cls, *, sink: PublishSink) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._builders = {"publish": self._build_publish}
        return self

    def _build_publish(self, spec: Mapping[str, object]) -> DecoratorFactory[WireEvent]:
        """Build the ``publish`` factory, bound to this registry's sink."""
        return PublishSpec.from_wire(spec).factory_for(self._sink)

    def resolve(self, spec: Mapping[str, object]) -> DecoratorFactory[WireEvent]:
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
