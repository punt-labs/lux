"""The ops-surface Protocol the topic (pub-sub) commands read.

Split out of :mod:`punt_lux.commands._ports` (lux-03k6): topic publish,
subscribe, unsubscribe, and receive are already their own command modules
(``topic_publish.py``, ``topic_subscribe.py``, ``topic_unsubscribe.py``,
``topic_recv.py``); giving the family's Protocol its own module matches
that existing per-command-family split.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import Scope
    from punt_lux.operations.models import OpError
    from punt_lux.operations.models.pubsub import PublishRequest, Received
    from punt_lux.operations.models.pubsub_acks import (
        Published,
        Subscribed,
        Unsubscribed,
    )

__all__ = ["TopicOps"]


@runtime_checkable
class TopicOps(Protocol):
    """The ops surface the topic commands read."""

    def publish(
        self, topic: str, request: PublishRequest, *, scope: Scope
    ) -> Published | OpError:
        """Fan a payload out to a topic's subscribers (reserved topics refused)."""
        ...

    def subscribe(self, topic: str, *, scope: Scope) -> Subscribed | OpError:
        """Subscribe the caller's session to a topic (reserved topics refused)."""
        ...

    def unsubscribe(self, topic: str, *, scope: Scope) -> Unsubscribed | OpError:
        """Unsubscribe the caller's session from a topic (reserved topics refused)."""
        ...

    def receive(self, *, scope: Scope) -> Received:
        """Take the next business event for the caller's session."""
        ...
