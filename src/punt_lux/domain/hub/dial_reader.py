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
from punt_lux.domain.hub.reply_sink import REPLY_TYPES

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

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
        """Read and route until stopped or the stream ends, then retire the dial."""
        generation = self._generation
        try:
            while not self._stopping.is_set() and not generation.is_closed:
                try:
                    data = generation.poll_chunk(_POLL_SECONDS)
                except (ConnectionClosedError, OSError, ValueError) as exc:
                    self._read_ended(exc)
                    break
                if data is not None and not self._routed(data):
                    break
        finally:
            self._connection.close_if_current(generation)

    def _read_ended(self, exc: Exception) -> None:
        """Say why a read ended; a deliberate close is not a break."""
        endpoint = self._generation.endpoint
        if self._stopping.is_set() or self._generation.is_closed:
            logger.debug("Listener exiting: the connection was closed (%s)", exc)
        elif isinstance(exc, ConnectionClosedError):
            logger.info("Listener exiting: display %s closed the connection", endpoint)
        else:
            logger.warning("Listener exiting: read from %s failed: %s", endpoint, exc)

    def _routed(self, data: bytes) -> bool:
        """Route every message ``data`` completes, each as it is decoded.

        A frame that cannot be decoded cannot be skipped -- the stream has no
        way to say where the next one starts -- so the dial is retired and the
        reconnect begins on a frame boundary. A frame of a kind a display never
        sends (a scene, say) is refused on its raw type before any decoding and
        ends the dial the same way. Returns whether the stream is still good.
        """
        generation = self._generation
        messages = generation.messages(data)
        while not self._stopping.is_set():
            try:
                msg = next(messages, None)
            except Exception:  # wire boundary: any decoder failure ends the stream
                logger.exception(
                    "Listener closing: display %s sent a malformed frame: %r",
                    generation.endpoint,
                    generation.head(_HEAD_BYTES),
                )
                return False
            if msg is None:
                return True
            if not self._routed_one(msg):
                return False
        return False

    def _routed_one(self, msg: Message) -> bool:
        """Hand one decoded message to its route; whether the stream is still good.

        A business event or interaction whose handler raises costs that message:
        the stream is sound and the next frame is waiting. A reply that cannot be
        routed is never skipped -- the next reply would then be matched to the
        wrong request -- so it ends the dial.
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
            return not isinstance(msg, REPLY_TYPES)
        return True
