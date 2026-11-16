"""A local program on a pseudo-terminal, driven without threads.

Lux's Display runs a single thread that polls its sockets once per frame
with a zero-timeout ``select`` (DES-002). A terminal fits that model:
``pump()`` does the same for the PTY, spending at most a small time budget
(2 ms) and byte budget per frame, so a flood of output (``yes``, a large
``cat``) can't stall a frame, yet the program isn't starved either.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import pwd
import select
import signal
import struct
import termios
import time
from collections.abc import Sequence

__all__ = ["PtyProcess", "user_environment"]

DEFAULT_BUDGET = 4 << 20  # bytes read per frame, at most
DEFAULT_TIME_BUDGET_S = 0.002  # read time per frame, at most (of ~16 ms)
_REFILL_WAIT_S = 0.002  # how long to wait for more output before returning
_CHUNK = 64 * 1024
_HANGUP_GRACE_S = 0.3  # per signal, while closing


# Display-process settings a user's shell must not inherit (found live: with
# the spike's isolated HOME, `cd ~` landed in the Display's state directory and
# zsh skipped ~/.zshrc, so there was no completion).
_DISPLAY_ONLY_VARS = ("LUX_SOCKET", "TERM_PROGRAM", "TERM_PROGRAM_VERSION")


def user_environment() -> dict[str, str]:
    """The environment for a user's program: their real login identity.

    The Display may run with a different ``HOME`` (an isolated instance, or a
    launchd service with a minimal environment), so ``HOME``, ``USER``,
    ``LOGNAME`` and ``SHELL`` come from the password database for the
    current user, not from the Display's own environment.
    """
    entry = pwd.getpwuid(os.getuid())
    env = {k: v for k, v in os.environ.items() if k not in _DISPLAY_ONLY_VARS}
    env.update(
        HOME=entry.pw_dir,
        USER=entry.pw_name,
        LOGNAME=entry.pw_name,
        SHELL=entry.pw_shell or "/bin/sh",
        TERM="xterm-256color",
        COLORTERM="truecolor",
    )
    return env


class PtyProcess:
    """A child process on a PTY, with non-blocking pump, write, resize, close."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        cols: int = 80,
        rows: int = 24,
        budget: int = DEFAULT_BUDGET,
        time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    ) -> None:
        self.budget = budget
        self.time_budget_s = time_budget_s
        env = user_environment()
        argv = list(argv) if argv else [env["SHELL"], "-l"]
        self.pid, self._fd = pty.fork()
        if self.pid == 0:  # child
            os.execvpe(argv[0], argv, env)  # noqa: S606 -- argv is the caller's command
        os.set_blocking(self._fd, False)
        self.resize(cols, rows)
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def pump(self) -> bytes:
        """Return the program's output, reading for at most ``time_budget_s``.

        Reads until the byte budget or the time budget is spent, or no more
        output arrives within ``_REFILL_WAIT_S``. Reading only what is ready
        *right now* was the original design, and it throttled heavy output to
        about 0.1-0.5 MB/s: a macOS PTY buffers only about 1 KB, so the program
        filled it and then slept until the next frame (STEP3.md, "PTY
        throughput"). Waiting briefly for the refill keeps it flowing.
        """
        out = bytearray()
        deadline = time.monotonic() + self.time_budget_s
        while self._alive and len(out) < self.budget:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            # Wait for a refill only once output is flowing: an idle terminal
            # must cost nothing, or every quiet terminal would add 2 ms a frame.
            wait = min(_REFILL_WAIT_S, left) if out else 0.0
            ready, _, _ = select.select([self._fd], [], [], wait)
            if not ready:
                break
            try:
                data = os.read(self._fd, min(_CHUNK, self.budget - len(out)))
            except BlockingIOError:
                break
            except OSError:  # EIO: the child exited and the PTY closed
                data = b""
            if not data:
                self._alive = False
                break
            out += data
        return bytes(out)

    def write(self, data: bytes) -> None:
        """Send input to the program."""
        if self._alive and data:
            try:
                os.write(self._fd, data)
            except OSError:
                self._alive = False

    def resize(self, cols: int, rows: int) -> None:
        """Tell the program its window size (it receives SIGWINCH)."""
        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self) -> None:
        """Hang up the program and reap it, without blocking for long.

        SIGHUP, a short wait, then SIGKILL. Never a blocking ``waitpid``: an
        interactive shell that ignored SIGHUP once hung the whole Display on
        exit (STEP3.md).
        """
        if self._alive:
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.kill(self.pid, sig)
                except ProcessLookupError:
                    break
                if self._reaped_within(_HANGUP_GRACE_S):
                    break
            self._alive = False
        with contextlib.suppress(OSError):
            os.close(self._fd)

    def _reaped_within(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return True  # already reaped
            if pid:
                return True
            time.sleep(0.02)
        return False
