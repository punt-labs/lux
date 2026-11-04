"""``PublishOnClick`` — the click handler that publishes a button's declaration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.event_protocol import Event
    from punt_lux.domain.handlers.publish_sink import PublishSink
    from punt_lux.protocol.elements.publish_source import PublishSource

__all__ = ["PublishOnClick"]


@final
class PublishOnClick:
    """A click handler that publishes its owner's current declaration via a sink.

    It holds the owner, never a copy of the declaration, so patching the
    declaration changes what the next click publishes and a stale topic has
    nowhere to live. Serializable so it survives the Hub-to-Display native-pickle
    wire: on the Display its whole click bucket is wrapped for remote dispatch, so
    this never runs there; on the Hub it fires the real publish. A no-op sink (the
    agent tier) makes it inert without a separate branch.
    """

    _sink: PublishSink
    _source: PublishSource
    __slots__ = ("_sink", "_source")

    def __new__(cls, sink: PublishSink, source: PublishSource) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._source = source
        return self

    def __call__(self, _event: Event) -> None:
        """Publish the owner's current declaration; a cleared one publishes nothing."""
        declaration = self._source.publish
        if declaration is not None:
            self._sink(declaration.topic, declaration.payload)

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (PublishOnClick, (self._sink, self._source))
