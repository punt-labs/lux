"""ListenerThread -- the background thread that reads the display's messages.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): the link owns the connection and what it sends; reading what comes
back on a daemon thread, until it is stopped or the socket goes away, is a
separate concern. The thread reads through the connection, which owns the
socket (it can change across a reconnect) and serializes a read against a send,
and hands every decoded message to ``route`` as it is decoded.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import FrameReader
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ListenerThread"]

_JOIN_TIMEOUT = 2.0
# How long one wait for the display runs before the loop re-checks its stop flag.
_POLL_SECONDS = 0.1
# How much of a malformed frame the log shows.
_HEAD_BYTES = 64


@final
class ListenerThread:
    """Start, stop and run the read loop over the link's current connection."""

    _connection: DisplayConnection
    _route: Callable[[Message], None]
    # None = never started (or stopped and joined); a dead thread is kept so
    # callers can tell "started and has since exited" from "never started".
    _thread: threading.Thread | None
    # One per thread: a thread that outlived stop() keeps its own, set, and
    # exits when its handler returns, whatever a later start() does.
    _stopping: threading.Event
    __slots__ = ("_connection", "_route", "_stopping", "_thread")

    def __new__(
        cls, connection: DisplayConnection, route: Callable[[Message], None]
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._route = route
        self._thread = None
        self._stopping = threading.Event()
        return self

    @property
    def started(self) -> bool:
        """Whether a thread was started and has not been stopped and joined."""
        return self._thread is not None

    @property
    def alive(self) -> bool:
        """Whether the thread is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_current(self) -> bool:
        """Whether the caller is the listener thread itself."""
        return self._thread is threading.current_thread()

    def start(self) -> None:
        """Start the thread; a no-op if it is already running.

        A thread that :meth:`stop` could not join is told to stop and is no
        longer the listener: it is abandoned, loudly, and a new one started.
        """
        if self.alive:
            if not self._stopping.is_set():
                return
            logger.error(
                "Abandoning a listener thread that did not stop; starting a new one"
            )
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(self._stopping,), name="lux-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread and wait for it, if running."""
        thread = self._thread
        if thread is None:
            return
        self._stopping.set()
        thread.join(timeout=_JOIN_TIMEOUT)
        if thread.is_alive():
            logger.warning("Listener thread did not exit within timeout")
        else:
            self._thread = None

    def _run(self, stopping: threading.Event) -> None:
        """Read messages from the connection and route them until told to stop."""
        reader = FrameReader()
        while not stopping.is_set():
            if not self._connection.is_open:
                logger.debug("Listener exiting: connection is closed")
                break
            try:
                data = self._connection.poll_chunk(_POLL_SECONDS)
            except (OSError, ValueError) as exc:
                logger.warning("Listener exiting: read failed: %s", exc)
                break
            if data is None:
                continue
            if not data:
                logger.info(
                    "Listener exiting: display %s closed the connection",
                    self._connection.endpoint,
                )
                break
            reader.feed(data)
            if not self._routed(reader):
                break

    def _routed(self, reader: FrameReader) -> bool:
        """Route every message the reader holds, each as it is decoded.

        A frame that cannot be decoded cannot be skipped -- the stream has no
        way to say where the next one starts -- so the connection is closed on
        purpose and the reconnect begins on a frame boundary. A frame of a kind
        a display never sends (a scene, say) is refused on its raw type before
        any decoding and ends the connection the same way. Returns whether the
        stream is still good.
        """
        messages = reader.iter_typed(DISPLAY_VOCABULARY)
        while True:
            try:
                msg = next(messages, None)
            except Exception:  # wire boundary: any decoder failure ends the stream
                logger.exception(
                    "Listener closing: display %s sent a malformed frame: %r",
                    self._connection.endpoint,
                    reader.head(_HEAD_BYTES),
                )
                self._connection.close()
                return False
            if msg is None:
                return True
            self._routed_one(msg)

    def _routed_one(self, msg: Message) -> None:
        """Hand one decoded message to its route; a raising route costs that message.

        The stream is sound and the next frame is waiting, so a handler's failure
        is logged with the message it failed on and the listener keeps serving.
        """
        try:
            self._route(msg)
        except Exception:
            logger.exception(
                "Listener route failed on %s from display %s; continuing",
                type(msg).__name__,
                self._connection.endpoint,
            )
