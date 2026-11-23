"""SessionWatch — the promise an applet makes to leave when its session does.

An applet is spawned by the session-start hook and immediately reparented away
from it, so nothing in the process tree ties the two together afterwards. Without
something that does, a session that ends leaves a program running against the
Hub for as long as the machine is up, and the next session adds another.

The tie is the session's own process id, handed to the applet at spawn. The
applet asks the operating system whether that process still exists, on a bounded
interval, and exits when it does not. Nothing is written to disk, nothing has to
be cleaned up, and the check costs a signal-zero.

Watching the process rather than being told by a hook is deliberate. A hook fires
when a session ends *cleanly*; a session that crashes, or is killed, never fires
one — and that is exactly the case that leaves an orphan. The window is the poll
interval, which is the bound the design promises. The Hub's lease is the backstop
underneath: a session's menu entry is swept when it stops renewing, whether or
not its applet noticed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Protocol, Self, final, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["NoSession", "SessionEnd", "SessionWatch"]

# How often to ask whether the session is still there. The interval is the whole
# bound on an orphan's life, and the check is a signal-zero, so this can be short
# without costing anything worth measuring.
_POLL_SECONDS = 5.0


@runtime_checkable
class SessionEnd(Protocol):
    """What tells an applet its time is up."""

    async def until_session_ends(self) -> None:
        """Return when the applet should stop serving."""
        ...


@final
class NoSession:
    """Nothing to watch: the applet was run by hand, and its terminal ends it.

    The Null Object for the one case with no session behind it. A developer
    running ``lux-beads`` in a terminal is the tie themselves — Ctrl-C is the
    stop — so this never returns rather than inventing a deadline nobody asked
    for.
    """

    __slots__ = ()

    async def until_session_ends(self) -> None:
        """Never return: nothing here will ever end the applet."""
        await asyncio.Event().wait()


@final
class SessionWatch:
    """Watch a session's process, and end this one when it goes."""

    _session_pid: int
    _poll_seconds: float
    __slots__ = ("_poll_seconds", "_session_pid")

    def __new__(cls, session_pid: int, poll_seconds: float = _POLL_SECONDS) -> Self:
        self = super().__new__(cls)
        self._session_pid = session_pid
        self._poll_seconds = poll_seconds
        return self

    @property
    def session_is_alive(self) -> bool:
        """Whether the watched session process still exists.

        ``kill(pid, 0)`` is the portable existence check: it delivers nothing and
        raises only when there is no such process. A process this one may not
        signal still exists, which is the answer being asked for, so the
        permission error is a yes.
        """
        try:
            os.kill(self._session_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    async def until_session_ends(self) -> None:
        """Return once the watched session is gone, having polled until then."""
        while self.session_is_alive:
            await asyncio.sleep(self._poll_seconds)
        logger.info("session %d has gone; the applet is leaving", self._session_pid)
