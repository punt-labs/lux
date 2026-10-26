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
)
from punt_lux.domain.hub.reply_sink import REPLY_TYPES, ReplyOutOfOrderError

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.display_listener import DisplayListener
    from punt_lux.domain.hub.reply_sink import Pending
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
        retired while waiting, or after it was retired for a frame a display may
        not send, a reply out of order, or a frame that cannot be decoded: a peer
        that did one of those cannot be trusted with the rest of the stream.
        """
        if self._listener.is_current:
            err = "Cannot wait for a reply from the listener thread"
            raise RuntimeError(err)
        while True:
            remaining = deadline - time.monotonic()
            if generation.has_reader:
                return generation.await_reply(pending, remaining)
            with generation.inline_reading() as granted:
                if granted:
                    try:
                        return self._read_inline(generation, pending, deadline)
                    finally:
                        self._settle_if_ended(generation)
            if remaining <= 0:
                return None
            reply = generation.await_reply(pending, min(remaining, _SLOT_RETRY_SECONDS))
            if reply is not None:
                return reply

    def run_held(self) -> None:
        """Run the interactions inline reads held; call with no request lock held."""
        self._listener.run_held()

    def _settle_if_ended(self, generation: DialGeneration) -> None:
        """Settle a dial someone ended while this read held its reader slot.

        The end was recorded and no one else could read the dial's ledger whole: this
        reader had the slot, so it reads to the end and settles before it lets go.
        """
        if generation.ended is not None and not generation.is_settled:
            self._listener.settle(generation, inline=True)

    def _read_inline[R: Message](
        self, generation: DialGeneration, pending: Pending[object, R], deadline: float
    ) -> R | None:
        """Read ``generation``'s socket until ``pending`` is answered or time is up.

        The same routing the listener applies, so the ack ledger stays in step
        with the wire. This is the dial's reader for the time it holds the slot, so a
        dial ended under it, or by a failed read, is settled here after reading to the
        end what it holds; an undecodable frame ends the dial as the reader would,
        naming who ended it the way the reader does.
        """
        while not generation.answered(pending):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if generation.ended is not None:  # someone ended it: settle it as reader
                self._listener.settle(generation, inline=True)
                raise generation.closed_error()
            try:
                chunk = generation.poll_chunk(min(remaining, _POLL_SECONDS))
                if chunk is not None:
                    self._route_inline(generation, chunk)
            except (ConnectionClosedError, OSError) as exc:
                # The display's end, or the dial ended under the wait: either way it is
                # over. An end another recorded first is reported as that one's cause.
                self._listener.settle(generation, inline=True)
                if generation.ended != "display":
                    raise generation.closed_error() from exc
                raise
            except ReplyOutOfOrderError as exc:
                # The stream skewed: the Hub gives up on a dial it can no longer
                # match replies on, and the display is not blamed for it.
                msg = f"{generation.endpoint} sent a reply nobody was owed"
                raise self._ended_stream(generation, "hub", HubRetiredError(msg)) from exc
            except (ValueError, KeyError, TypeError) as exc:
                # A frame the stream cannot be trusted past: the display sent it,
                # so the display ended the dial, and the caller learns it as one.
                msg = f"{generation.endpoint} sent a frame that broke its stream"
                raise self._ended_stream(
                    generation, "display", ConnectionClosedError(msg)
                ) from exc
            except Exception:  # re-raised: the dial's stream cannot be trusted
                self._connection.close_if_current(generation, cause="hub")
                raise
        return generation.await_reply(pending, 0.0)

    def _ended_stream(
        self,
        generation: DialGeneration,
        cause: RetireCause,
        error: ConnectionClosedError,
    ) -> ConnectionClosedError:
        """End a dial whose stream this reader cannot trust; the error to raise.

        The cause is recorded first. An end that lost to another's reports the
        winner's cause, the way a writer's does, not this reader's own.
        """
        won = generation.end(cause)
        self._connection.close_if_current(generation, cause=cause)
        return error if won else generation.closed_error()

    def _route_inline(self, generation: DialGeneration, chunk: bytes) -> None:
        """Route every message ``chunk`` completes; a raising reply ends the dial.

        A retired dial stops routing the rest of its chunk: nothing after the point
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
