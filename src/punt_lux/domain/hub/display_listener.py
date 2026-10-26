"""DisplayListener -- what the display pushes: events and interactions, and who reads.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`: the link
sends and waits; this is the side that the display speaks into unprompted. It
owns the reader thread over the current dial, the interaction handlers a click is
answered by, and the business events a subscriber polls. A business event outlives
the dial that carried it; a reply does not, and is not this object's business
(see :class:`~punt_lux.domain.hub.display_replies.DisplayReplies`).
"""

from __future__ import annotations

import functools
import queue
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.domain.hub.listener_thread import ListenerThread

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.polled_event import PolledEvent
    from punt_lux.protocol import Message, RemoteEventHandlerInvocation

__all__ = ["DisplayListener"]


@final
class DisplayListener:
    """The reader over the current dial, and where what it reads is routed."""

    _connection: DisplayConnection
    _handlers: InteractionHandlers
    _inbound: InboundRouter
    _thread: ListenerThread
    _budget: float
    __slots__ = ("_budget", "_connection", "_handlers", "_inbound", "_thread")

    def __new__(cls, connection: DisplayConnection, budget: float) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._handlers = InteractionHandlers()
        self._inbound = InboundRouter(self._handlers)
        self._thread = ListenerThread(connection, self._inbound.route)
        self._budget = budget
        return self

    @property
    def is_current(self) -> bool:
        """Whether the caller is the reader thread itself."""
        return self._thread.is_current

    def route(self, generation: DialGeneration, msg: Message, *, inline: bool) -> None:
        """Route ``msg``, read from ``generation``, to where it is waited for.

        ``inline`` marks a message a waiting caller decoded while holding request
        locks: an interaction is then held (see :meth:`run_held`), not run.
        """
        self._inbound.route(generation, msg, inline=inline)

    def settle(self, generation: DialGeneration, *, inline: bool) -> bool:
        """Settle a dial this caller reads, after reading to the end what it holds.

        For a reader that is not the listener thread: it holds the dial's reader
        slot, and what it routes is held or run as ``inline`` says. The cause that
        stands is the one already recorded on the dial; a dial nobody has ended is
        ended by the display, since this is called on a read that found it so, and
        that is recorded before the drain, as the listener thread records it.
        Returns whether this call settled it.
        """
        generation.end("display")
        recorded = generation.ended or "display"
        if recorded != "hub":
            DialDrain(functools.partial(self._inbound.route, inline=inline)).run(
                generation
            )
        return self._connection.close_if_current(generation, cause=recorded)

    def settle_unread(self, generation: DialGeneration) -> None:
        """Settle a dial someone ended, if no reader holds it, by reading it here.

        A dial born with no listener and with no inline read in flight has no reader,
        and a death found by a writer's failure or the keepalive must not be lost for
        lack of one: the discoverer takes the reader slot itself. When a reader holds
        the slot, it notices the end and settles the dial.
        """
        if not self._connection.holds(generation):
            return  # a redial replaced it: its own reader settles it, or already did
        with generation.inline_reading() as granted:
            if granted:
                self.settle(generation, inline=True)

    def run_held(self) -> None:
        """Run the interactions an inline read held, outside every request lock."""
        self._inbound.run_held()

    def start(self) -> None:
        """Start a reader on the current dial; a no-op if it already has one."""
        self._thread.start()

    def start_on(self, born: DialGeneration) -> None:
        """Start a reader on ``born``, a dial made holding the listener's slot.

        A dial with no reader repairs nothing: if the reader cannot start, the dial
        this call was given is retired and the error raised, so the next connect
        redials.
        """
        try:
            self._thread.start_on(born)
        except BaseException:
            self._connection.retire(born, cause="hub")
            raise

    def stop(self) -> None:
        """Stop the reader and retire its dial, if running."""
        self._thread.stop()

    def set_fallback_handler(
        self, handler: Callable[[RemoteEventHandlerInvocation], None]
    ) -> None:
        """Install the handler every interaction the display reports is given to.

        Called by the Hub to route display-side clicks through Hub-side element
        dispatch; with none installed an interaction is dropped.
        """
        self._handlers.set_fallback(handler)

    def poll_event(self, timeout: float | None = None) -> PolledEvent:
        """Block for the next subscribed business event (a :class:`PolledEvent`).

        Raises ``TimeoutError`` after ``timeout`` seconds (default the standing
        budget). A reader that was started and has since ended is still the
        no-event case: events it queued are delivered first, then the
        ``TimeoutError`` names the exit. One that was never started raises
        ``RuntimeError`` (observer messages are push-only), or
        :class:`ConnectionClosedError` when the link is not even connected.
        """
        if not self._thread.started:
            self._connection.require()
            err = (
                "poll_event requires an active listener — "
                "connect with listen=True first"
            )
            raise RuntimeError(err)
        t = self._budget if timeout is None else timeout
        try:
            return self._inbound.next_event(t)
        except queue.Empty as exc:
            if not self._thread.alive:
                err = (
                    f"no business event arrived within {t}s "
                    "and the listener thread has exited"
                )
            else:
                err = f"no business event arrived within {t}s"
            raise TimeoutError(err) from exc
