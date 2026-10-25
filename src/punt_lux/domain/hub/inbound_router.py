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
    # Interactions an inline read decoded: they run later, on a thread that holds
    # none of the request model's locks.
    _held: queue.SimpleQueue[RemoteEventHandlerInvocation]
    __slots__ = ("_events", "_handlers", "_held")

    def __new__(cls, handlers: InteractionHandlers) -> Self:
        self = super().__new__(cls)
        self._handlers = handlers
        self._events = queue.SimpleQueue()
        self._held = queue.SimpleQueue()
        return self

    def next_event(self, timeout: float) -> PolledEvent:
        """Block up to ``timeout`` for the next business event.

        Raises :class:`queue.Empty` when none arrives in time.
        """
        return self._events.get(timeout=timeout)

    def route(
        self, generation: DialGeneration, msg: Message, *, inline: bool = False
    ) -> None:
        """Send ``msg``, read from ``generation``, to its destination by kind.

        ``inline`` marks a message a caller waiting on the socket decoded while
        holding request locks and the reader slot. Its interaction is held, not
        run: a handler may reach the registry or the store, which no thread
        holding those may do. :meth:`run_held` runs it afterwards.
        """
        if isinstance(msg, RemoteEventHandlerInvocation):
            if inline:
                self._held.put(msg)
            else:
                self._handlers.run(msg)
        elif isinstance(msg, ObserverMessage):
            self._events.put(PolledEvent(topic=msg.topic, payload=msg.payload))
        elif isinstance(msg, REPLY_TYPES):
            generation.deliver(msg)
        else:
            logger.debug("Dropping unhandled message: %s", type(msg).__name__)

    def run_held(self) -> None:
        """Run the interactions an inline read held, on the calling thread."""
        while True:
            try:
                held = self._held.get_nowait()
            except queue.Empty:
                return
            self._handlers.run(held)
