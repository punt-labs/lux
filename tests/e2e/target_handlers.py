"""Picklable view-logic handlers the harness wires onto a target element.

The harness needs the target element's Hub-side handler chain to do two
separable things on one interaction: run UI/view logic AND announce a
business topic (target.md §Event Models, loop invariants I3 and I6). Two
handlers carry the two halves:

- ``RecordingClickHandler`` — the view half. It counts fires so the
  harness can assert the UI-handler mechanism (D21) ran, and ran exactly
  once, independently of pub-sub.
- ``PublishingHandler`` — the business half for scenarios announcing a
  payload of the app's own design. The wire ``publish`` declaration sends
  the interaction (its kind, scene, element, and fields); an app that wants
  to announce something else — a ticket id, a domain command — wires this
  handler instead: a real Hub-side handler that publishes ``payload`` to
  ``topic`` through the production ``HubPublishSink`` → ``hub.publish``.

Both are serializable classes (not closures) because the Hub's
authoritative element tree crosses the wire to build the Display replica;
the handler chain must survive native pickling, exactly like the shipped
``_PublishWrappedHandler`` and ``HubPublishSink``. On the replica the
pickled copy never fires — it is folded into a ``RemoteDispatchGroup``
that only sends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.handlers.publish_sink import PublishSink

__all__ = ["PublishingHandler", "RecordingClickHandler"]


class RecordingClickHandler:
    """Record each fired event so the harness can assert the UI mechanism.

    The Hub fires this against its authoritative element copy; the test
    holds the same instance and reads ``fire_count`` to prove the
    element's handler dispatch (D21) ran — and ran exactly once. Only the
    count is kept, never the event object: the handler is re-serialized on
    every whole-scene re-push, and the ``ButtonClicked``/``ValueChanged``
    events are not designed to cross the wire.
    """

    _count: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._count = 0
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), {"_count": self._count})

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, _event: object) -> None:
        """Count the fire — the view-logic side effect of the click."""
        self._count += 1

    @property
    def fire_count(self) -> int:
        """Return how many times the Hub fired this handler."""
        return self._count


class PublishingHandler:
    """Publish an app-authored ``payload`` to ``topic`` when the Hub fires it.

    A real Hub-side handler: on each fire it calls the production
    ``PublishSink`` (a ``HubPublishSink`` bound to the owning connection),
    which reaches ``hub.publish`` and fans the payload out to that
    connection's subscribers. This is target.md's "a Hub-side handler may
    publish an application event" — an announcement in the app's own terms,
    which the wire ``publish`` declaration cannot make because what it sends
    is the interaction.
    """

    _sink: PublishSink
    _topic: str
    _payload: Mapping[str, object]

    def __new__(
        cls, *, sink: PublishSink, topic: str, payload: Mapping[str, object]
    ) -> Self:
        self = super().__new__(cls)
        self._sink = sink
        self._topic = topic
        self._payload = payload
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (
            object.__new__,
            (type(self),),
            {"_sink": self._sink, "_topic": self._topic, "_payload": self._payload},
        )

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, _event: object) -> None:
        """Publish the payload — the business side effect of the click."""
        self._sink(self._topic, self._payload)
