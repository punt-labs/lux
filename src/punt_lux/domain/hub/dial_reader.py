"""DialReader -- reads one dial's messages and routes them, until the dial ends.

The reader is bound to the generation it was made for: it reads that generation's
socket and nothing else, hands every decoded message to ``route`` together with
that generation, and when it ends -- told to stop, the display closed the stream,
a frame could not be decoded, a reply could not be routed -- it settles its own
generation through the :class:`~punt_lux.domain.hub.settler.Settler` the dial's reader
slot gave it, a no-op if a redial already replaced it. So a reader that outlived a
redial can never close, read or answer for the new dial.
The thread that drives it is :class:`~punt_lux.domain.hub.listener_thread.
ListenerThread`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.finally_guard import FinallyGuard
from punt_lux.domain.hub.reply_sink import REPLY_TYPES
from punt_lux.domain.programmer_error import ProgrammerError

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.settler import Settler
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

    _generation: DialGeneration
    _settler: Settler
    _route: Callable[[DialGeneration, Message], None]
    _stopping: threading.Event
    __slots__ = ("_generation", "_route", "_settler", "_stopping")

    def __new__(
        cls,
        generation: DialGeneration,
        settler: Settler,
        route: Callable[[DialGeneration, Message], None],
        stopping: threading.Event,
    ) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._settler = settler
        self._route = route
        self._stopping = stopping
        return self

    def run(self) -> None:
        """Read and route until stopped or the dial ends, then settle the dial.

        Whatever ended the loop, the dial is settled by the settler this reader
        holds: it drains the socket, fixes the cause and takes the ledger, a no-op
        once a redial replaced the generation. A stream this reader gave up on (a
        frame that did not decode, a reply nobody was owed) is not read again, and is
        ended undrained. The loop's own exit on its stop flag is the Hub's end and is
        requested first, so the decision has a cause; someone else's end (a writer's
        failure, the keepalive's give-up, the Hub's request) is noticed at the top of
        the loop and is settled here, after the drain, not by whoever found it.
        """
        gave_up: RetireCause | None = None
        with FinallyGuard(
            lambda: (
                self._settler.settle()
                if gave_up is None
                else self._settler.end_stream(gave_up)
            ),
            f"settling the dial to {self._generation.endpoint}",
        ):
            gave_up = self._read()

    def _read(self) -> RetireCause | None:
        """Read until the dial ends; who ended a stream this reader gave up on."""
        generation = self._generation
        try:
            while not self._stopping.is_set():
                if generation.is_closed:
                    return None  # someone else's end or request: settle it
                try:
                    data = generation.poll_chunk(_POLL_SECONDS)
                except (ConnectionClosedError, OSError, ValueError) as exc:
                    if self._read_ended(exc):
                        # Recorded the moment the reader learns of it, before it
                        # drains: a Hub request arriving now cannot make it the Hub's.
                        generation.end("display")
                    else:
                        # A stop or a close the read raced: the settle needs a cause
                        # or a request to start from, or it has nothing to decide.
                        generation.request_hub()
                    return None
                ended = None if data is None else self._routed(data)
                if ended is not None:
                    return ended
        except BaseException:
            generation.request_hub()  # an unexpected failure is the Hub's own
            raise
        generation.request_hub()  # the stop flag: the Hub's own end
        return None

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
        way to say where the next one starts -- so the dial is ended and the
        reconnect begins on a frame boundary: the display sent it, so the display
        ended the dial. A frame of a kind a display never sends (a scene, say) is
        refused on its raw type before any decoding and ends the dial the same way.
        Returns ``None`` while the stream is still good, else who ended it. A chunk the
        loop stops reading because the reader was told to stop, or the dial was
        settled under it, is not the stream's end: the reader's loop notices.
        """
        generation = self._generation
        messages = generation.messages(data)
        # A settled dial parks no reply, and the undecoded rest of its chunk is not
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

        A dial that is ending refuses *replies* only: its sink parks none. A business
        event or an interaction belongs to the link, not to the dial that carried it,
        so one the display had already sent is delivered even as its dial ends.
        """
        try:
            self._route(self._generation, msg)
        except ProgrammerError:
            raise  # a broken rule ends the reader loudly; it is not the message's
        except Exception:
            logger.exception(
                "Listener route failed on %s from display %s: %s",
                type(msg).__name__,
                self._generation.endpoint,
                repr(msg)[:_HEAD_REPR],
            )
            return "hub" if isinstance(msg, REPLY_TYPES) else None
        return None
