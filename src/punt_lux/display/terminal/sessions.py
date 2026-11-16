"""Named terminal sessions owned by the Display: a stand-in for ``luxd-pty``.

A ``terminal`` element only *names* a session; the session (a PTY plus its
``TerminalView``) lives here, keyed by that name, so re-rendering the element
every frame, or showing the same session in another frame, reuses one
program. The render loop pumps every session once per frame
(``pump_all``), before painting.

Spike limitation (ADR-0006): sessions live inside the Display process, so
they die when it restarts. The target design moves them into a separate
``luxd-pty`` daemon that streams snapshot-then-bytes to whichever Display
attaches; that is step 4.
"""

from __future__ import annotations

import shlex
import time
from typing import ClassVar

from punt_lux.display.terminal.pty import PtyProcess
from punt_lux.display.terminal.view import TerminalView

__all__ = ["TerminalSession", "TerminalSessions"]

# Written into the terminal when its program exits: dim, on a fresh line.
_ENDED_NOTICE = b"\r\n\x1b[2m[process exited]\x1b[0m"


class TerminalSession:
    """One program on a PTY, and the view that renders it."""

    def __init__(self, name: str, command: str) -> None:
        self.name = name
        self.process = PtyProcess(shlex.split(command) if command else None)
        self.view = TerminalView()
        self.view.on_input = self.process.write
        self.view.on_resize = self.process.resize
        self.bytes_in = 0
        self.ended = False  # the program exited; the terminal stays, read-only

    def pump(self) -> bool:
        """Move ready output into the view. True if there was any."""
        data = self.process.pump()
        if data:
            self.bytes_in += len(data)
            self.view.feed(data)
        if not self.process.alive and not self.ended:
            self.ended = True
            self.view.feed(_ENDED_NOTICE)
            return True
        return bool(data)

    def close(self) -> None:
        self.process.close()


class TerminalSessions:
    """The Display's sessions, by name (one per Display process)."""

    _sessions: ClassVar[dict[str, TerminalSession]] = {}
    last_output_at: ClassVar[float] = 0.0  # monotonic time of the last output

    @classmethod
    def get(cls, name: str, command: str) -> TerminalSession:
        """The session called ``name``, started on first use.

        An exited session is kept, not restarted: ``exit`` in the shell must
        end the terminal (found live; it used to respawn the next frame).
        The view shows that the program ended; the frame stays until closed.
        """
        session = cls._sessions.get(name)
        if session is None:
            session = TerminalSession(name, command)
            cls._sessions[name] = session
        return session

    @classmethod
    def pump_all(cls) -> bool:
        """Pump every session once. True if any produced output this frame."""
        busy = False
        for session in list(cls._sessions.values()):
            busy |= session.pump()
        if busy:
            cls.last_output_at = time.monotonic()
        return busy

    @classmethod
    def close_all(cls) -> None:
        for session in cls._sessions.values():
            session.close()
        cls._sessions.clear()
