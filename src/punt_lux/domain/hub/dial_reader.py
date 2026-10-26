"""DialReader -- reads one dial's messages and routes them, until the dial ends.

The reader is bound to the generation it was made for: it reads that generation's
socket and nothing else, hands every decoded message to ``route`` together with
that generation, and when it ends -- told to stop, the display closed the stream,
a frame could not be decoded, a reply could not be routed -- it retires its own
generation with ``close_if_current``, a no-op if a redial already replaced it. So
a reader that outlived a redial can never close, read or answer for the new dial.
The thread that drives it is :class:`~punt_lux.domain.hub.listener_thread.
ListenerThread`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.reply_sink import REPLY_TYPES

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["DialReader"]

# How long one wait for the display runs before the loop re-checks its stop flag.
_POLL_SECONDS = 0.1
# How much of a malformed frame the log shows.
_HEAD_BYTES = 64
# How much of a message that a route failed on the log shows.
_HEAD_REPR = 200


@final
class DialReader:
    """The read loop over one generation."""

    _connection: DisplayConnection
    _generation: DialGeneration
    _route: Callable[[DialGeneration, Message], None]
    _stopping: threading.Event
    __slots__ = ("_connection", "_generation", "_route", "_stopping")

    def __new__(
        cls,
        connection: DisplayConnection,
        generation: DialGeneration,
        route: Callable[[DialGeneration, Message], None],
        stopping: threading.Event,
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._generation = generation
        self._route = route
        self._stopping = stopping
        return self

    def run(self) -> None:
        """Read and route until stopped or the dial ends, then settle the dial.

        The closing report is ``close_if_current`` of this reader's own generation,
        taken whatever ended the loop: it is a no-op once a redial replaced the
        generation, and ``stop`` settles it first, so safety rests on that scoping
        and not on re-testing the stopping flag before the report. Someone else's end
        (a writer's failure, the keepalive's give-up) is noticed at the top of the
        loop, and is settled here, after the drain, not by whoever found it.
        """
        generation = self._generation
        cause: RetireCause = "hub"  # the Hub's own stop, or a stream it gave up on
        readable = True  # whether the socket may still hold something worth reading
        try:
            while not self._stopping.is_set():
                if (recorded := generation.ended) is not None:
                    cause = recorded
                    break
                try:
                    data = generation.poll_chunk(_POLL_SECONDS)
                except (ConnectionClosedError, OSError, ValueError) as exc:
                    if self._read_ended(exc):
                        cause = "display"
                        # Recorded the moment the reader learns of it, before it drains:
                        # a Hub end arriving now loses, and leaves the ledger to us.
                        generation.end(cause)
                    break
                ended = None if data is None else self._routed(data)
                if ended is not None:
                    cause = ended
                    generation.end(cause)
                    readable = False  # a stream we gave up on has nothing to trust
                    break
        finally:
            self._settle(cause, readable=readable)

    def _settle(self, cause: RetireCause, *, readable: bool) -> None:
        """Read what the socket still holds if it is owed, then settle the dial.

        The cause that stands is the first one recorded on the dial, which is not
        always this reader's own. A stream that could not be read past (a frame that
        did not decode, a reply nobody was owed) is not read again.
        """
        generation = self._generation
        if readable and (generation.ended or cause) != "hub":
            DialDrain(self._route).run(generation)
        self._connection.close_if_current(generation, cause=generation.ended or cause)

    def _read_ended(self, exc: Exception) -> bool:
        """Say why a read ended; whether the display ended it.

        A deliberate close (the Hub's own, or a dial retired under the read) is
        not the display's doing and not a break.
        """
        endpoint = self._generation.endpoint
        if self._stopping.is_set() or self._generation.is_closed:
            logger.debug("Listener exiting: the connection was closed (%s)", exc)
            return False
        if isinstance(exc, ConnectionClosedError):
            logger.info("Listener exiting: display %s closed the connection", endpoint)
        else:
            logger.warning("Listener exiting: read from %s failed: %s", endpoint, exc)
        return True

    def _routed(self, data: bytes) -> RetireCause | None:
        """Route every message ``data`` completes, each as it is decoded.

        A frame that cannot be decoded cannot be skipped -- the stream has no
        way to say where the next one starts -- so the dial is retired and the
        reconnect begins on a frame boundary: the display sent it, so the display
        ended the dial. A frame of a kind a display never sends (a scene, say) is
        refused on its raw type before any decoding and ends the dial the same way.
        Returns ``None`` while the stream is still good, else who ended it. A chunk the
        loop stops reading because the reader was told to stop, or the dial was
        settled under it, is not the stream's end: the reader's loop notices.
        """
        generation = self._generation
        messages = generation.messages(data)
        # A retired dial parks no reply, and the undecoded rest of its chunk is not
        # routed. What was already routed stands: an event or an interaction is
        # link-level, not the dial's reply (see ``_routed_one``).
        while not self._stopping.is_set() and not generation.is_settled:
            try:
                msg = next(messages, None)
            except Exception:  # wire boundary: any decoder failure ends the stream
                logger.exception(
                    "Listener closing: display %s sent a malformed frame: %r",
                    generation.endpoint,
                    generation.head(_HEAD_BYTES),
                )
                return "display"
            if msg is None:
                return None
            ended = self._routed_one(msg)
            if ended is not None:
                return ended
        return None

    def _routed_one(self, msg: Message) -> RetireCause | None:
        """Hand one decoded message to its route; ``None`` while the stream is good.

        A business event or interaction whose handler raises costs that message:
        the stream is sound and the next frame is waiting. A reply that cannot be
        routed is never skipped -- the next reply would then be matched to the
        wrong request -- so it ends the dial, and it is the Hub that ends it: the
        stream skewed, or the Hub's own routing failed.

        Retirement orders delivery of *replies* only: a retired dial's sink
        refuses them. A business event or an interaction belongs to the link, not
        to the dial that carried it (rule 16), so one the display had already sent
        is delivered even as its dial retires.
        """
        try:
            self._route(self._generation, msg)
        except Exception:
            logger.exception(
                "Listener route failed on %s from display %s: %s",
                type(msg).__name__,
                self._generation.endpoint,
                repr(msg)[:_HEAD_REPR],
            )
            return "hub" if isinstance(msg, REPLY_TYPES) else None
        return None
