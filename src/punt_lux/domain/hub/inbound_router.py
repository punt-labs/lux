"""InboundRouter -- where every message the display sends back is routed to.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): the link owns the socket and the listener thread that reads it;
what becomes of a received message is a separate concern. An interaction is
answered by the :class:`~punt_lux.domain.hub.interaction_handlers.InteractionHandlers`
it was given; a business event queues for :meth:`next_event`; an ack, pong or
query response queues for the caller blocked on it.
"""

from __future__ import annotations

import logging
import queue
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.reply_queues import ReplyQueues
from punt_lux.polled_event import PolledEvent
from punt_lux.protocol import (
    AckMessage,
    ObserverMessage,
    PongMessage,
    QueryResponse,
    RemoteEventHandlerInvocation,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["InboundRouter"]


@final
class InboundRouter:
    """Route received messages to their handlers, event queue or reply queue."""

    _handlers: InteractionHandlers
    _replies: ReplyQueues
    _events: queue.SimpleQueue[PolledEvent]

    def __new__(cls, handlers: InteractionHandlers) -> Self:
        self = super().__new__(cls)
        self._handlers = handlers
        self._replies = ReplyQueues()
        self._events = queue.SimpleQueue()
        return self

    def next_event(self, timeout: float) -> PolledEvent:
        """Block up to ``timeout`` for the next business event.

        Raises :class:`queue.Empty` when none arrives in time.
        """
        return self._events.get(timeout=timeout)

    def next_ack(self, timeout: float) -> AckMessage | None:
        """Block up to ``timeout`` for the next ack; ``None`` on timeout."""
        return self._replies.get_ack(timeout)

    def next_reply[T: Message](self, expected: type[T], timeout: float) -> T | None:
        """Block up to ``timeout`` for the next ``expected`` reply."""
        return self._replies.get_typed(expected, timeout)

    def reset(self) -> None:
        """Discard stragglers a dying listener left, on connection close.

        A dying listener may still be mid-put; replacing the event queue
        outright (rather than draining it) can never race that put, and any
        straggler it lands in is simply collected with the old queue.
        """
        self._replies.drain()
        self._events = queue.SimpleQueue()

    def route(self, msg: Message) -> None:
        """Send ``msg`` to its destination by kind; unknown kinds are dropped."""
        if isinstance(msg, RemoteEventHandlerInvocation):
            self._handlers.run(msg)
        elif isinstance(msg, ObserverMessage):
            self._events.put(PolledEvent(topic=msg.topic, payload=msg.payload))
        elif isinstance(msg, (AckMessage, PongMessage, QueryResponse)):
            self._replies.put(msg)
        else:
            logger.debug("Dropping unhandled message: %s", type(msg).__name__)
