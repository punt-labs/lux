"""InboundRouter -- where every message the display sends back is routed to.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): the link owns the socket and the listener thread that reads it;
what becomes of a received message is a separate concern. An interaction is
answered by the :class:`~punt_lux.domain.hub.interaction_handlers.InteractionHandlers`
it was given; a business event queues for :meth:`next_event`; an ack, pong or
query response goes to the sink of the generation it was read from, which matches
it to the request it answers.

Interactions and business events are link-level: they outlive a dial. A reply is
generation-level: it is delivered into the sink of the dial that carried it, never
a later one's.
"""

from __future__ import annotations

import logging
import queue
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.reply_sink import REPLY_TYPES
from punt_lux.polled_event import PolledEvent
from punt_lux.protocol import ObserverMessage, RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["InboundRouter"]


@final
class InboundRouter:
    """Route received messages to their handlers, event queue or reply sink."""

    _handlers: InteractionHandlers
    _events: queue.SimpleQueue[PolledEvent]
    __slots__ = ("_events", "_handlers")

    def __new__(cls, handlers: InteractionHandlers) -> Self:
        self = super().__new__(cls)
        self._handlers = handlers
        self._events = queue.SimpleQueue()
        return self

    def next_event(self, timeout: float) -> PolledEvent:
        """Block up to ``timeout`` for the next business event.

        Raises :class:`queue.Empty` when none arrives in time.
        """
        return self._events.get(timeout=timeout)

    def route(self, generation: DialGeneration, msg: Message) -> None:
        """Send ``msg``, read from ``generation``, to its destination by kind."""
        if isinstance(msg, RemoteEventHandlerInvocation):
            self._handlers.run(msg)
        elif isinstance(msg, ObserverMessage):
            self._events.put(PolledEvent(topic=msg.topic, payload=msg.payload))
        elif isinstance(msg, REPLY_TYPES):
            generation.sink.deliver(msg)
        else:
            logger.debug("Dropping unhandled message: %s", type(msg).__name__)
