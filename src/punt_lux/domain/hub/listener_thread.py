"""ListenerThread -- the background thread that reads the display's messages.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): the link owns the connection and what it sends; reading what comes
back on a daemon thread, until it is stopped or the socket goes away, is a
separate concern. The thread reads whatever socket the link currently holds
(it can change across a reconnect), reads through the connection so a read is
never interleaved with a send, and hands every decoded message to ``route``.
"""

from __future__ import annotations

import logging
import select
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import FrameReader

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ListenerThread"]

_JOIN_TIMEOUT = 2.0


@final
class ListenerThread:
    """Start, stop and run the read loop over the link's current socket."""

    _connection: DisplayConnection
    _route: Callable[[Message], None]
    # None = never started (or stopped and joined); a dead thread is kept so
    # callers can tell "started and has since exited" from "never started".
    _thread: threading.Thread | None
    _stopping: threading.Event

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
        """Start the thread; a no-op if it is already running."""
        if self.alive:
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, name="lux-listener", daemon=True
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

    def _run(self) -> None:
        """Read messages from the socket and route them until told to stop."""
        reader = FrameReader()
        while not self._stopping.is_set():
            sock = self._connection.current
            if sock is None:
                logger.debug("Listener exiting: socket is None")
                break
            try:
                readable, _, _ = select.select([sock], [], [], 0.1)
            except (OSError, ValueError) as exc:
                logger.warning("Listener exiting: select failed: %s", exc)
                break
            if not readable:
                continue
            try:
                data = self._connection.read_chunk(sock)
            except OSError as exc:
                logger.warning("Listener exiting: recv failed: %s", exc)
                break
            if not data:
                logger.debug("Listener exiting: server closed connection")
                break
            reader.feed(data)
            for msg in reader.drain_typed():
                self._route(msg)
