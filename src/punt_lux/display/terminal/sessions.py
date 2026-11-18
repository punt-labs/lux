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
from typing import ClassVar, Self

from punt_lux.display.terminal.view import TerminalView
from punt_lux.ptyd.holder import PtyHolder as PtyProcess

__all__ = ["TerminalSession", "TerminalSessions"]

# Time per frame spent reading all terminals' output, at most. Of a 16.7 ms
# frame at 60 fps; measured (STEP3.md): 6 ms lets one `yes` flood reach about
# 44 MB/s while keeping ~54 fps.
FRAME_READ_BUDGET_S = 0.006

# Written into the terminal when its program exits: dim, on a fresh line.
_ENDED_NOTICE = b"\r\n\x1b[2m[process exited]\x1b[0m"


class TerminalSession:
    """One program on a PTY, and the view that renders it."""

    _name: str
    _process: PtyProcess
    _view: TerminalView
    _bytes_in: int
    _ended: bool
    _had_output: bool

    def __new__(cls, name: str, command: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._process = PtyProcess(shlex.split(command) if command else None)
        self._view = TerminalView()
        self._view.on_input = self._process.write
        self._view.on_resize = self._process.resize
        self._bytes_in = 0
        self._ended = False  # the program exited; the terminal stays, read-only
        self._had_output = False  # in the last pump: schedules busy sessions last
        return self

    def pump(self) -> bool:
        """Move ready output into the view. True if there was any."""
        data = self._process.pump()
        if data:
            self._bytes_in += len(data)
            self._view.feed(data)
        if not self._process.alive and not self._ended:
            self._ended = True
            self._view.feed(_ENDED_NOTICE)
            return True
        return bool(data)

    def close(self) -> None:
        self._process.close()
        self._view.close()

    @property
    def name(self) -> str:
        return self._name

    @property
    def process(self) -> PtyProcess:
        return self._process

    @property
    def view(self) -> TerminalView:
        return self._view

    @property
    def bytes_in(self) -> int:
        return self._bytes_in

    @bytes_in.setter
    def bytes_in(self, value: int) -> None:
        self._bytes_in = value

    @property
    def ended(self) -> bool:
        return self._ended

    @ended.setter
    def ended(self, value: bool) -> None:
        self._ended = value

    @property
    def had_output(self) -> bool:
        return self._had_output

    @had_output.setter
    def had_output(self, value: bool) -> None:
        self._had_output = value


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
    def pump_all(cls, frame_budget_s: float = FRAME_READ_BUDGET_S) -> bool:
        """Pump every session once. True if any produced output this frame.

        The frame has one read budget for all terminals. Quiet sessions (no
        output last frame) go first and return almost at once; each session
        gets an equal share of the time *left*, so the busy ones inherit what
        the quiet ones didn't use. One flood next to idle terminals gets
        nearly the whole budget; many floods together can't exceed it.
        """
        live = sorted(
            (s for s in cls._sessions.values() if not s.ended),
            key=lambda s: s.had_output,
        )
        if not live:
            return False
        deadline = time.monotonic() + frame_budget_s
        busy = False
        for remaining, session in zip(range(len(live), 0, -1), live, strict=True):
            left = deadline - time.monotonic()
            session.process.time_budget_s = max(0.0, left / remaining)
            session.had_output = session.pump()
            busy |= session.had_output
        if busy:
            cls.last_output_at = time.monotonic()
        return busy

    @classmethod
    def close_all(cls) -> None:
        for session in cls._sessions.values():
            session.close()
        cls._sessions.clear()
