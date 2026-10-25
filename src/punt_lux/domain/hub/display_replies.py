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

from punt_lux.domain.hub.reply_sink import REPLY_TYPES

if TYPE_CHECKING:
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

    def await_reply(
        self, generation: DialGeneration, pending: Pending, deadline: float
    ) -> Message | None:
        """Wait until ``deadline`` for ``pending``'s reply on ``generation``.

        ``None`` on the deadline. Raises ``RuntimeError`` on the listener thread
        (it is the only producer of the replies this would wait for, so the wait
        could never end), :class:`ConnectionClosedError` when the dial is retired
        while waiting, and the decoder's error (after retiring the dial) for a
        frame a display may not send or that cannot be decoded: a peer that sent
        one cannot be trusted with the rest of the stream.
        """
        if self._listener.is_current:
            err = "Cannot wait for a reply from the listener thread"
            raise RuntimeError(err)
        while True:
            remaining = deadline - time.monotonic()
            if generation.has_reader:
                return generation.sink.await_reply(pending, remaining)
            with generation.inline_reading() as granted:
                if granted:
                    return self._read_inline(generation, pending, deadline)
            if remaining <= 0:
                return None
            reply = generation.sink.await_reply(
                pending, min(remaining, _SLOT_RETRY_SECONDS)
            )
            if reply is not None:
                return reply

    def _read_inline(
        self, generation: DialGeneration, pending: Pending, deadline: float
    ) -> Message | None:
        """Read ``generation``'s socket until ``pending`` is answered or time is up.

        The same routing the listener applies, so the ack ledger stays in step
        with the wire. A failed read or an undecodable frame retires the dial, as
        the reader would.
        """
        while pending.reply is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                chunk = generation.poll_chunk(remaining)
                if chunk is not None:
                    self._route_inline(generation, chunk)
            except Exception:  # re-raised: the dial's stream cannot be trusted
                self._connection.close_if_current(generation)
                raise
        return pending.reply

    def _route_inline(self, generation: DialGeneration, chunk: bytes) -> None:
        """Route every message ``chunk`` completes; a raising reply ends the dial."""
        for msg in generation.messages(chunk):
            try:
                self._listener.route(generation, msg)
            except Exception:
                if isinstance(msg, REPLY_TYPES):
                    raise
                logger.exception(
                    "Inline route failed on %s from display %s",
                    type(msg).__name__,
                    generation.endpoint,
                )
