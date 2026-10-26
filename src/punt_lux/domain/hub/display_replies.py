"""DisplayReplies -- waiting on a dial for the reply one request is owed.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`: a caller
that sent a request waits here for the reply the request's own dial owes it --
from the dial's sink when a listener reads it, from the dial's socket directly
when none does. A dial has one reader at a time: an inline read holds the dial's
reader slot for its duration, so it never shares the frame buffer with a listener
or with another caller's inline read, and a caller that cannot take the slot waits
on the sink the holder feeds. What an inline read decodes is routed exactly as the
listener would route it (a click reaches the handlers, an event its queue).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
    UnresponsiveError,
)
from punt_lux.domain.hub.reply_sink import REPLY_TYPES
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.display_listener import DisplayListener
    from punt_lux.domain.hub.pending import Pending
    from punt_lux.domain.hub.settler import Settler
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["DisplayReplies"]

# How long a caller that could not take the reader slot waits on the sink before
# trying for the slot again (the holder may have finished with its own reply).
_SLOT_RETRY_SECONDS = 0.05
# How long one wait on the socket runs before the dial is checked for an end that
# someone else recorded (an end by a writer or the keepalive wakes no one).
_POLL_SECONDS = 0.1


@final
class DisplayReplies:
    """The waiting side of one display link."""

    _connection: DisplayConnection
    _listener: DisplayListener
    __slots__ = ("_connection", "_listener")

    def __new__(cls, connection: DisplayConnection, listener: DisplayListener) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._listener = listener
        return self

    def await_reply[R: Message](
        self, generation: DialGeneration, pending: Pending[object, R], deadline: float
    ) -> R | None:
        """Wait until ``deadline`` for ``pending``'s reply on ``generation``.

        ``None`` on the deadline. Raises ``RuntimeError`` on the listener thread
        (it is the only producer of the replies this would wait for, so the wait
        could never end) and :class:`ConnectionClosedError` when the dial is
        ended while waiting, or after it was ended for a frame a display may
        not send, a reply out of order, or a frame that cannot be decoded: a peer
        that did one of those cannot be trusted with the rest of the stream.
        """
        if self._listener.is_current:
            err = "Cannot wait for a reply from the listener thread"
            raise RuntimeError(err)
        while True:
            remaining = deadline - time.monotonic()
            slot = self._connection.reading(generation)
            if slot is None or slot.has_listener:
                # A dial no longer current is read by no one; a listener's dial is
                # read by the listener: either way the sink carries the reply.
                return generation.await_reply(pending, remaining)
            with slot.inline(self._listener.held_route) as settler:
                if settler is not None:
                    return self._read_inline(generation, pending, deadline, settler)
            if remaining <= 0:
                return None
            reply = generation.await_reply(pending, min(remaining, _SLOT_RETRY_SECONDS))
            if reply is not None:
                return reply

    def run_held(self) -> None:
        """Run the interactions inline reads held; call with no request lock held."""
        self._listener.run_held()

    def _read_inline[R: Message](
        self,
        generation: DialGeneration,
        pending: Pending[object, R],
        deadline: float,
        settler: Settler,
    ) -> R | None:
        """Read ``generation``'s socket until ``pending`` is answered or time is up.

        The same routing the listener applies, so the ack ledger stays in step
        with the wire. This is the dial's reader for the time it holds the slot, so a
        dial ended under it, or by a failed read, is settled here by ``settler`` after
        reading to the end what it holds; an end that lands after the last look is
        settled when the slot is let go, which honours the debt it left. An
        undecodable frame ends the dial as the reader would, naming who ended it the
        way the reader does.
        """
        while not generation.answered(pending):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if generation.is_closed:  # someone ended it: settle it as reader
                settler.settle()
                raise generation.closed_error()
            try:
                chunk = generation.poll_chunk(min(remaining, _POLL_SECONDS))
                if chunk is not None:
                    self._route_inline(generation, chunk)
            except Exception as exc:  # the dial's stream cannot be trusted past it
                error = self._ended_by(generation, settler, exc)
                if error is exc:
                    raise
                raise error from exc
        return generation.await_reply(pending, 0.0)

    @staticmethod
    def _ended_by(
        generation: DialGeneration, settler: Settler, exc: Exception
    ) -> Exception:
        """Settle the dial an inline read failed on; the error its caller is given.

        The display's end, or the dial ended under the wait, is over either way: a
        read that found the end is the display's, recorded before the drain, and an
        end another recorded first is reported as that one's. A reply nobody was owed
        skewed the stream: the Hub gives up on a dial it can no longer match replies
        on, and the display is not blamed. A frame that cannot be decoded is the
        display's, who sent it. Anything else is the Hub's own failure.
        """
        if isinstance(exc, ConnectionClosedError | OSError):
            if not generation.is_closed:
                generation.end("display")
            settler.settle()
            stands = generation.closed_error()
            return (
                stands
                if isinstance(stands, HubRetiredError | UnresponsiveError)
                else exc
            )
        if isinstance(exc, ReplyOutOfOrderError):
            msg = f"{generation.endpoint} sent a reply nobody was owed"
            won = settler.end_stream("hub")
            return HubRetiredError(msg) if won else generation.closed_error()
        if isinstance(exc, ValueError | KeyError | TypeError):
            msg = f"{generation.endpoint} sent a frame that broke its stream"
            won = settler.end_stream("display")
            return ConnectionClosedError(msg) if won else generation.closed_error()
        settler.end_stream("hub")
        return exc

    def _route_inline(self, generation: DialGeneration, chunk: bytes) -> None:
        """Route every message ``chunk`` completes; a raising reply ends the dial.

        A settled dial stops routing the rest of its chunk: nothing after the point
        the stream was given up on can be matched to a request, and a reply it was
        owed is refused by its sink. Events and interactions are link-level, not
        the dial's: one already routed (or held, see ``run_held``) is delivered
        whichever dial carried it (rule 16).
        """
        for msg in generation.messages(chunk):
            if generation.is_settled:
                return  # a settled dial routes nothing more
            try:
                self._listener.route(generation, msg, inline=True)
            except Exception:
                if isinstance(msg, REPLY_TYPES):
                    raise
                logger.exception(
                    "Inline route failed on %s from display %s",
                    type(msg).__name__,
                    generation.endpoint,
                )
