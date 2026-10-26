"""DialDrain -- the last look at a dial's socket before its ledger is taken.

The display acks a scene after a swap and may die a moment later, so an ack can be in
the socket's queue, or in the reader's buffer, when something ends the dial. Reading
to end of file does not find it (a display that is alive never sends one), and the
ledger would then charge a scene the display had already acked. So the dial's own
reader reads whatever the socket holds, without waiting, and routes every message it
completes, an ack to the dial's ledger and an interaction to the link, before it
takes the ledger and shuts the socket.
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

    def run(self, generation: DialGeneration) -> None:
        """Route every complete message ``generation`` holds, buffered or in the socket.

        The frames the reader had already taken off the socket and not yet routed
        come first, then whatever the socket holds now, and then it stops. A frame
        that cannot be decoded ends the drain: the stream cannot be trusted past it,
        and what the ledger owes stays as it is. So does a reply that fails to route
        (every later reply would be matched to the wrong entry), as it does for the
        reader. An event or an interaction that fails to route costs only itself.
        """
        chunk: bytes | None = b""  # the first pass routes what is already buffered
        while chunk is not None:
            try:
                for msg in generation.messages(chunk):
                    try:
                        self._route(generation, msg)
                    except Exception:
                        logger.exception(
                            "Drain route failed on %s from display %s",
                            type(msg).__name__,
                            generation.endpoint,
                        )
                        if isinstance(msg, REPLY_TYPES):
                            return
            except Exception:  # wire boundary: any decoder failure ends the stream
                logger.exception(
                    "Drain of %s stopped: its stream could not be read past %r",
                    generation.endpoint,
                    generation.head(64),
                )
                return
            chunk = generation.drain_chunk()
