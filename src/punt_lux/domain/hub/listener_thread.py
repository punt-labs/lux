"""ListenerThread -- the daemon thread that drives a :class:`DialReader`.

Extracted from :class:`~punt_lux.domain.hub.display_link.DisplayLink`
(PY-IC-6): the link owns the connection and what it sends; running a reader on a
daemon thread, until it is stopped or its dial ends, is a separate concern. A
reader lives and dies with the generation it was started on, and each dial has
one reader, ever: stopping retires the dial, so a restart needs a new one.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_reader import DialReader

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ListenerThread"]

_JOIN_TIMEOUT = 2.0


@final
class ListenerThread:
    """Start, stop and run the read loop over the link's current dial."""

    _connection: DisplayConnection
    _route: Callable[[DialGeneration, Message], None]
    # None = never started (or stopped and joined); a dead thread is kept so
    # callers can tell "started and has since exited" from "never started".
    _thread: threading.Thread | None
    # The generation the thread was started on, retired when it is stopped.
    _generation: DialGeneration | None
    # One per thread: a thread that outlived stop() keeps its own, set, and
    # exits when its handler returns, whatever a later start() does.
    _stopping: threading.Event
    __slots__ = ("_connection", "_generation", "_route", "_stopping", "_thread")

    def __new__(
        cls,
        connection: DisplayConnection,
        route: Callable[[DialGeneration, Message], None],
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._route = route
        self._thread = None
        self._generation = None
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

    def start(self, born: DialGeneration | None = None) -> None:
        """Start a reader on the current dial; a no-op if it already has one.

        ``born`` is the generation a ``DisplayConnection.open(listening=True)``
        just made: it holds the reader slot for this listener already, so there is
        nothing to claim or wait for, and the reader starts on exactly that dial.
        If it was retired in the gap, :class:`ConnectionClosedError` is raised and
        nothing starts on its replacement.

        A dial has one reader, ever: a thread that :meth:`stop` could not join has
        retired its dial, so the successor needs a new dial, and starting without
        one raises :class:`ConnectionClosedError`.
        """
        if born is None:
            generation = self._connection.require()
            if not generation.claim_reader():
                return
        else:
            generation = born
            if generation.is_closed:
                msg = f"the dial to {generation.endpoint} was retired before its reader"
                raise ConnectionClosedError(msg)
        if self.alive:
            logger.error(
                "Abandoning a listener thread that did not stop; starting a new one"
            )
        self._stopping = threading.Event()
        self._generation = generation
        reader = DialReader(self._connection, generation, self._route, self._stopping)
        thread = threading.Thread(target=reader.run, name="lux-listener", daemon=True)
        try:
            thread.start()
        except BaseException:
            generation.release_reader()  # no reader runs: do not claim there is one
            raise
        self._thread = thread

    def stop(self) -> None:
        """Stop the thread, retire its dial, and wait for the thread, if running.

        The dial is retired first: that wakes a reader blocked in ``recv`` and
        fails every waiter, so the join is short.
        """
        thread = self._thread
        if thread is None:
            return
        self._stopping.set()
        generation = self._generation
        if generation is not None:
            self._connection.close_if_current(generation)
        thread.join(timeout=_JOIN_TIMEOUT)
        if thread.is_alive():
            logger.warning("Listener thread did not exit within timeout")
        else:
            self._thread = None
