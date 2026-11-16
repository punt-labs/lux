"""A local program on a pseudo-terminal, driven without threads.

Lux's Display runs a single thread that polls its sockets once per frame
with a zero-timeout ``select`` (DES-002). A terminal fits that model:
``pump()`` does the same for the PTY and never blocks, and reads at most
``budget`` bytes per call, so a flood of output (``yes``, a large ``cat``)
can't stall a frame. The rest stays in the kernel buffer for the next frame.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time
from collections.abc import Sequence

__all__ = ["PtyProcess"]

DEFAULT_BUDGET = 256 * 1024  # bytes read per frame, at most
_CHUNK = 64 * 1024
_HANGUP_GRACE_S = 0.3  # per signal, while closing


class PtyProcess:
    """A child process on a PTY, with non-blocking pump, write, resize, close."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        cols: int = 80,
        rows: int = 24,
        budget: int = DEFAULT_BUDGET,
    ) -> None:
        self.budget = budget
        argv = list(argv) if argv else [os.environ.get("SHELL", "/bin/zsh"), "-l"]
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        env.pop("TERM_PROGRAM", None)  # don't claim to be the parent terminal
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
        """Return whatever output is ready now, up to ``budget`` bytes."""
        out = bytearray()
        while self._alive and len(out) < self.budget:
            ready, _, _ = select.select([self._fd], [], [], 0)
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
