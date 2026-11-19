"""Transports for a single-threaded frame loop (the Lux constraint: no reader thread).

The host calls pump() once per frame; it does a zero-timeout select() and reads
at most `budget` bytes, so a flood can never stall the UI.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import termios
from collections.abc import Iterator
from typing import Protocol

import replay


class Transport(Protocol):
    def pump(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    def close(self) -> None: ...
    @property
    def alive(self) -> bool: ...


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
        if self._alive:
            try:
                os.kill(self.pid, signal.SIGHUP)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            self._alive = False
        os.close(self.fd)


class ReplayTransport:
    """Plays a recording at real time (60 fps frames); input is discarded."""

    def __init__(self, name: str, budget: int = 256 * 1024, loop: bool = True) -> None:
        self.rec = replay.load(name)
        self.budget, self.loop = budget, loop
        self._it: Iterator[bytes] = replay.frames(self.rec, budget)
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def pump(self) -> bytes:
        try:
            return next(self._it)
        except StopIteration:
            if not self.loop:
                self._alive = False
                return b""
            self._it = replay.frames(self.rec, self.budget)
            return b"\x1bc"  # reset, then start again next frame

    def write(self, data: bytes) -> None:
        pass

    def resize(self, cols: int, rows: int) -> None:
        pass

    def close(self) -> None:
        self._alive = False


class ShowcaseTransport:
    """Cycles through several recordings, `seconds` each, forever (for a long demo)."""

    def __init__(self, names: list[str], seconds: float = 12.0, budget: int = 64 * 1024) -> None:
        import time

        self._time = time.monotonic
        self.names, self.seconds, self.budget = names, seconds, budget
        self._i = -1
        self._next()

    @property
    def current(self) -> str:
        return self.names[self._i]

    @property
    def alive(self) -> bool:
        return True

    def _next(self) -> None:
        self._i = (self._i + 1) % len(self.names)
        self._replay = ReplayTransport(self.current, budget=self.budget, loop=True)
        self._until = self._time() + self.seconds
        self._reset = True

    def pump(self) -> bytes:
        if self._time() >= self._until:
            self._next()
        if self._reset:
            self._reset = False
            return b"\x1bc"  # clear the screen between recordings
        return self._replay.pump()

    def write(self, data: bytes) -> None:
        pass

    def resize(self, cols: int, rows: int) -> None:
        pass

    def close(self) -> None:
        pass
