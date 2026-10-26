"""DialDrain -- the last look at a dial's socket before its ledger is taken.

The display acks a scene after a swap and may die a moment later, so an ack can be in
the socket's queue, or in the reader's buffer, when something ends the dial. The
ledger would then charge a scene the display had already acked. So the dial's own
reader reads whatever the socket holds, without waiting, and routes every message it
completes, an ack to the dial's ledger and an interaction to the link, before it
takes the ledger and shuts the socket. It also says whether it found the stream's end:
a display that was dead when the Hub looked is the display's end, never the Hub's.

The claim that the drain is complete holds for a same-host socket only. There a
display that dies leaves its end of file (or, if it died holding bytes the Hub had
sent, a reset) queued behind everything it had sent, so reading to that end reads
every ack. A reset from a remote peer may discard what was queued, so a cross-host
stream's drain is not complete and nothing here claims it is.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.reply_sink import REPLY_TYPES

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["DialDrain"]


@final
class DialDrain:
    """Read what a dial already holds and route it, then stop; never wait."""

    _route: Callable[[DialGeneration, Message], None]
    __slots__ = ("_route",)

    def __new__(cls, route: Callable[[DialGeneration, Message], None]) -> Self:
        self = super().__new__(cls)
        self._route = route
        return self

    def run(self, generation: DialGeneration) -> bool:
        """Route every complete message ``generation`` holds; whether its end came.

        The frames the reader had already taken off the socket and not yet routed
        come first, then whatever the socket holds, and then it stops at the point
        where the next read would block. ``True`` when the look found the stream's end
        (end of file, a reset, a TLS end of file), which includes a read that was cut
        short: it is never reported as "nothing more". A frame that cannot be decoded
        ends the drain with ``False``: the stream cannot be trusted past it, and what
        the ledger owes stays as it is. So does a reply that fails to route (every
        later reply would be matched to the wrong entry), as it does for the reader.
        An event or an interaction that fails to route costs only itself. Raises
        :class:`~punt_lux.domain.hub.drain_result.DrainIncompleteError` when a writer
        held the socket past the ceiling, so the last look could not be made; the
        settler, which catches it, leaves the capture to the bound.
        """
        chunk = b""  # the first pass routes what is already buffered
        while True:
            if not self._routed(self._route, generation, chunk):
                return False
            look = generation.drain()
            if look.ended:
                self._routed(self._route, generation, look.chunk)
                return True
            if not look.chunk:
                return False
            chunk = look.chunk

    @staticmethod
    def _routed(
        route: Callable[[DialGeneration, Message], None],
        generation: DialGeneration,
        chunk: bytes,
    ) -> bool:
        """Route every message ``chunk`` completes; ``False`` if the stream broke."""
        try:
            for msg in generation.messages(chunk):
                try:
                    route(generation, msg)
                except Exception:
                    logger.exception(
                        "Drain route failed on %s from display %s",
                        type(msg).__name__,
                        generation.endpoint,
                    )
                    if isinstance(msg, REPLY_TYPES):
                        return False
        except Exception:  # wire boundary: any decoder failure ends the stream
            logger.exception(
                "Drain of %s stopped: its stream could not be read past %r",
                generation.endpoint,
                generation.head(64),
            )
            return False
        return True
