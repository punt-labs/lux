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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_reader import DialReader

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.protocol import Message

logger = logging.getLogger(__name__)

__all__ = ["ListenerRun", "ListenerThread"]

_JOIN_TIMEOUT = 2.0


@dataclass(frozen=True, slots=True)
class ListenerRun:
    """One started reader: its thread, the dial it reads, and its own stop flag.

    One value, assigned once the thread has started, so the three can never
    disagree. Each run keeps its own flag: a thread that outlived ``stop`` exits
    when its handler returns, whatever a later start does.
    """

    thread: threading.Thread
    generation: DialGeneration
    stopping: threading.Event


@final
class ListenerThread:
    """Start, stop and run the read loop over the link's current dial."""

    _connection: DisplayConnection
    _route: Callable[[DialGeneration, Message], None]
    # None = never started (or stopped and joined); a dead thread's run is kept so
    # callers can tell "started and has since exited" from "never started".
    _run: ListenerRun | None
    __slots__ = ("_connection", "_route", "_run")

    def __new__(
        cls,
        connection: DisplayConnection,
        route: Callable[[DialGeneration, Message], None],
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._route = route
        self._run = None
        return self

    @property
    def started(self) -> bool:
        """Whether a thread was started and has not been stopped and joined."""
        return self._run is not None

    @property
    def alive(self) -> bool:
        """Whether the thread is running."""
        run = self._run
        return run is not None and run.thread.is_alive()

    @property
    def is_current(self) -> bool:
        """Whether the caller is the listener thread itself."""
        run = self._run
        return run is not None and run.thread is threading.current_thread()

    def start(self) -> None:
        """Start a reader on the current dial; a no-op if it already has one.

        A dial has one reader, ever: a thread that :meth:`stop` could not join has
        retired its dial, so the successor needs a new dial, and starting without
        one raises :class:`ConnectionClosedError`.
        """
        generation = self._connection.require()
        if generation.claim_reader():
            self._launch(generation)

    def start_on(self, born: DialGeneration) -> None:
        """Start a reader on ``born``, a dial made holding the reader slot already.

        There is nothing to claim or wait for. If the dial was retired in the gap,
        :class:`ConnectionClosedError` is raised and nothing starts on its
        replacement.
        """
        if born.is_closed:
            msg = f"the dial to {born.endpoint} was retired before its reader"
            raise ConnectionClosedError(msg)
        self._launch(born)

    def stop(self) -> None:
        """Stop the thread, retire its dial, and wait for the thread, if running.

        The dial is retired first: that wakes a reader blocked in ``recv`` and
        fails every waiter, so the join is short. A dial the display had already
        ended is left to the reader, which drains it and settles it before it exits.
        """
        run = self._run
        if run is None:
            return
        run.stopping.set()
        self._connection.retire(run.generation, cause="hub")
        run.thread.join(timeout=_JOIN_TIMEOUT)
        if run.thread.is_alive():
            logger.warning("Listener thread did not exit within timeout")
        else:
            self._run = None

    def _launch(self, generation: DialGeneration) -> None:
        """Run a reader over ``generation``, which holds the listener's slot."""
        if self.alive:
            logger.error(
                "Abandoning a listener thread that did not stop; starting a new one"
            )
        stopping = threading.Event()
        reader = DialReader(self._connection, generation, self._route, stopping)
        thread = threading.Thread(target=reader.run, name="lux-listener", daemon=True)
        # Published before the thread starts: it may run, and a ``stop`` may arrive,
        # before ``start`` returns, and both must find this run.
        previous = self._run
        self._run = ListenerRun(thread, generation, stopping)
        try:
            thread.start()
        except BaseException:
            self._run = previous
            generation.release_reader()  # no reader runs: do not claim there is one
            raise
