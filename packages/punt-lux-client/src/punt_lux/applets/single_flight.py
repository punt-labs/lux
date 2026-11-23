"""SingleFlight — one run at a time, and an answer for whoever arrives during it.

Clicks arrive faster than the work behind them finishes. Each one is answered on
its own, because each is a user's own click with its own budget — but the work
behind two clicks a second apart is one piece of work: the load already running
reads the same issues, and the board it produces lands in the frame the second
click has just raised. Starting it again would spawn a second ``bd`` for rows
the first is already fetching, and a user drumming on the menu entry would spawn
one per click.

So the slow half of a click runs here, and a caller who finds a run in flight is
told so rather than queued behind it. Queuing would start that caller's work at
the moment the user had stopped waiting for it, and would leave a queue to drain
after every burst.

The lock is never waited on. Every acquisition is a try, so a caller either owns
the run or is turned away at once; nothing blocks on it, and there is no second
lock for it to be ordered against.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["SingleFlight"]


@final
class SingleFlight:
    """The one run allowed at a time; a caller arriving during it is not queued."""

    _running: threading.Lock
    __slots__ = ("_running",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._running = threading.Lock()
        return self

    def ran(self, work: Callable[[], None]) -> bool:
        """Run *work* unless a run is in flight; say whether this call ran it.

        Standing down is an ordinary outcome rather than a failure, so it comes
        back as an answer rather than an exception: what to do instead is the
        caller's to say, and on this leg it is something the user is told.
        """
        if not self._running.acquire(blocking=False):
            return False
        try:
            work()
        finally:
            self._running.release()
        return True
