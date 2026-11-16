"""SPIKE: in-Display PTY sessions -- a stand-in for the future luxd-pty daemon.

One PTY + GhosttyTerminalView per session name, owned by the Display process
and pumped once per frame from the render loop (zero-timeout read, capped per
frame, no threads -- DES-002). Known spike limitation: sessions die with the
Display, which the real design (a separate luxd-pty) must not do.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import shlex
import signal
import struct
import termios
from typing import ClassVar

from punt_lux.display.terminal.ghostty_view import GhosttyTerminalView


class LocalPtyTransport:
    """A local shell behind a PTY, read non-blocking from the caller's thread."""

    def __init__(self, argv: list[str] | None = None, cols: int = 80, rows: int = 24,
                 budget: int = 256 * 1024) -> None:  # fmt: skip
        self.budget = budget
        argv = argv or [os.environ.get("SHELL", "/bin/zsh"), "-l"]
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        env.pop("TERM_PROGRAM", None)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(argv[0], argv, env)
        os.set_blocking(self.fd, False)
        self.resize(cols, rows)
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def pump(self) -> bytes:
        if not self._alive:
            return b""
        out = bytearray()
        while len(out) < self.budget:
            r, _, _ = select.select([self.fd], [], [], 0)
            if not r:
                break
            try:
                data = os.read(self.fd, min(65536, self.budget - len(out)))
            except BlockingIOError:
                break
            except OSError:  # EIO: child exited
                self._alive = False
                break
            if not data:
                self._alive = False
                break
            out += data
        return bytes(out)

    def write(self, data: bytes) -> None:
        if self._alive and data:
            try:
                os.write(self.fd, data)
            except OSError:
                self._alive = False

    def resize(self, cols: int, rows: int) -> None:
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self) -> None:
        """Hang up the shell and reap it, never blocking the caller for long.

        Bug found live in step 3: a blocking waitpid here froze the Display's
        exit when the shell (an interactive zsh in use) did not exit promptly
        on SIGHUP. Now: SIGHUP, poll briefly, then SIGKILL, and never wait
        without WNOHANG.
        """
        if self._alive:
            for sig, wait_s in ((signal.SIGHUP, 0.3), (signal.SIGKILL, 0.3)):
                try:
                    os.kill(self.pid, sig)
                except ProcessLookupError:
                    break
                if self._reaped_within(wait_s):
                    break
            self._alive = False
        try:
            os.close(self.fd)
        except OSError:
            pass

    def _reaped_within(self, seconds: float) -> bool:
        import time

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                return True
            if pid:
                return True
            time.sleep(0.02)
        return False


class TerminalSession:
    """A PTY and the Ghostty view rendering it."""

    def __init__(self, name: str, command: str) -> None:
        argv = shlex.split(command) if command else None
        self.name = name
        self.transport = LocalPtyTransport(argv)
        self.view = GhosttyTerminalView()
        self.view.on_input = self.transport.write
        self.view.on_resize = self.transport.resize
        self.bytes_in = 0

    def pump(self) -> bool:
        data = self.transport.pump()
        if data:
            self.bytes_in += len(data)
            self.view.feed(data)
        return bool(data)

    def close(self) -> None:
        self.transport.close()


class TerminalSessions:
    """Process-wide registry: session name -> TerminalSession (spike singleton)."""

    _sessions: ClassVar[dict[str, TerminalSession]] = {}
    last_output_at: ClassVar[float] = 0.0

    @classmethod
    def get(cls, name: str, command: str) -> TerminalSession:
        s = cls._sessions.get(name)
        if s is None or not s.transport.alive:
            if s is not None:
                s.close()
            s = TerminalSession(name, command)
            cls._sessions[name] = s
        return s

    @classmethod
    def pump_all(cls) -> bool:
        """Read every session's PTY once (call once per frame). True if any output."""
        import time

        busy = False
        for s in list(cls._sessions.values()):
            busy |= s.pump()
        if busy:
            cls.last_output_at = time.monotonic()
        return busy

    @classmethod
    def close_all(cls) -> None:
        for s in cls._sessions.values():
            s.close()
        cls._sessions.clear()
