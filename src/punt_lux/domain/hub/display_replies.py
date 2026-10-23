"""DisplayReplies -- waiting for what the display sends back, and ending what is left.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`: the link
sends; this is the receiving side. A caller that sent a request waits here for its
one typed reply, an ack, or the next business event -- from the listener's queues
when the listener runs, from the socket directly when it does not. The same object
ends the connection (the link closing it, or the listener finding the stream
broken), because ending it means discarding the replies queued behind it.
"""

from __future__ import annotations

import logging
import queue
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.domain.hub.listener_thread import ListenerThread
from punt_lux.protocol import AckMessage

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.polled_event import PolledEvent
    from punt_lux.protocol import Message, RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["DisplayReplies"]


@final
class DisplayReplies:
    """The receiving side of one display link."""

    _connection: DisplayConnection
    _handlers: InteractionHandlers
    _inbound: InboundRouter
    _listener: ListenerThread
    _budget: float
    __slots__ = ("_budget", "_connection", "_handlers", "_inbound", "_listener")

    def __new__(
        cls,
        connection: DisplayConnection,
        budget: float,
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._handlers = InteractionHandlers()
        self._inbound = InboundRouter(self._handlers)
        self._listener = ListenerThread(connection, self.route, self.end)
        self._budget = budget
        return self

    @property
    def listening(self) -> bool:
        """Whether the listener thread is running."""
        return self._listener.alive

    def start(self) -> None:
        """Start the listener thread; a no-op if it is already running."""
        self._listener.start()

    def stop(self) -> None:
        """Stop the listener thread, if running."""
        self._listener.stop()

    def route(self, msg: Message) -> None:
        """Send a message the display sent to where it is waited for."""
        self._inbound.route(msg)

    def set_fallback(
        self, handler: Callable[[RemoteEventHandlerInvocation], None]
    ) -> None:
        """Answer interactions with no callback registered for them with ``handler``."""
        self._handlers.set_fallback(handler)

    def end(self) -> None:
        """Close the socket and discard the stragglers; a no-op if already closed."""
        if self._connection.is_open:
            self._connection.close()
            self._inbound.reset()

    def typed[T: Message](self, expected: type[T], wait: float | None) -> T | None:
        """Wait for one ``expected`` reply, active listener or inline read.

        Both a ping and a query send a request and then wait for exactly one typed
        reply -- from the background listener's own queue when it is running, or an
        inline read loop when it is not, dropping any interleaved frame the inline
        path sees along the way. ``wait`` of ``None`` is the standing budget.
        """
        deadline = time.monotonic() + (self._budget if wait is None else wait)
        if self._listener.alive:
            remaining = deadline - time.monotonic()
            return self._inbound.next_reply(expected, remaining, self._listener)
        self._connection.require()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            received = self._connection.receive(remaining)
            if received is None:
                return None
            if isinstance(received, expected):
                return received
            kind = type(received).__name__
            logger.debug("%s: dropping interleaved %s frame", expected.__name__, kind)

    def ack(self) -> AckMessage | None:
        """Receive expecting an AckMessage.  Drops interleaved frames.

        Thread-safe.  When the listener is active, blocks on the reply queues.
        When inactive, reads directly from the socket and drops any non-ack frame
        that arrives in the meantime.

        Raises RuntimeError if called from the listener thread (would deadlock
        because the listener is the only ack producer).
        """
        if self._listener.is_current:
            err = "Cannot call blocking _recv_ack from the listener thread"
            raise RuntimeError(err)
        if self._listener.alive:
            return self._inbound.next_ack(self._budget, self._listener)
        self._connection.require()
        deadline = time.monotonic() + self._budget
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = self._connection.receive(remaining)
            if msg is None:
                return None
            if isinstance(msg, AckMessage):
                return msg
            logger.debug("_recv_ack: dropping interleaved %s frame", type(msg).__name__)

    def event(self, wait: float | None) -> PolledEvent:
        """Block for the next subscribed business event (a :class:`PolledEvent`).

        Raises ``TimeoutError`` after ``wait`` seconds (default the standing
        budget); requires a listener that was started (observer messages are
        push-only). Gates on the listener having started so a listener that
        started and has since exited surfaces as ``TimeoutError`` naming the exit,
        not a ``RuntimeError`` claiming it never started.
        """
        self._connection.require()
        if not self._listener.started:
            err = (
                "poll_event requires an active listener — "
                "call start_listener() after connect()"
            )
            raise RuntimeError(err)
        t = self._budget if wait is None else wait
        try:
            return self._inbound.next_event(t)
        except queue.Empty as exc:
            if not self._listener.alive:
                err = (
                    f"no business event arrived within {t}s "
                    "and the listener thread has exited"
                )
            else:
                err = f"no business event arrived within {t}s"
            raise TimeoutError(err) from exc
