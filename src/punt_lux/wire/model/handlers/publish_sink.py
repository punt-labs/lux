"""``PublishSink`` — where a ``publish``-decorated handler sends its event.

The structural contract the Hub satisfies through ``HubPublishSink``, which
routes into ``Hub.publish`` against the owning connection's scope. A test
injects any callable of the same shape to record the ``(topic, payload)`` pairs
a decorator emits.

Its own module because a couple of dozen element codecs name this type to wire
a decoder without importing the decorator that consumes it (PY-IC-9).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

__all__ = ["PublishSink"]


@runtime_checkable
class PublishSink(Protocol):
    """Structural contract for the ``publish`` decorator's sink."""

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        """Publish ``payload`` to ``topic`` in the decorator owner's scope."""
        ...
