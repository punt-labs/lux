"""One daemon-owned PTY: spawn, drain, input buffering, resize and reap.

No terminal parsing, socket transport or viewer policy lives here. The parent
reads on a nonblocking master; input is buffered across short writes. Exited
children are reaped independently of whether their last output was drained.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import pty
import select
import struct
import termios
import time
from collections.abc import Sequence
from typing import Never, Self

from punt_lux.ptyd.child import ChildLifetime
from punt_lux.ptyd.environment import user_environment
from punt_lux.ptyd.input_buffer import InputBuffer


class PtyHolder:
    """Owned PTY resource with bounded, single-threaded IO operations."""

    _child: ChildLifetime
    _fd: int
    _input: InputBuffer
    _reader_open: bool
    _closed: bool
    _budget: int
    _time_budget_s: float

    def __new__(
        cls,
        argv: Sequence[str] | None = None,
        *,
        cols: int = 80,
        rows: int = 24,
        budget: int = 4 * 1024 * 1024,
        time_budget_s: float = 0.002,
    ) -> Self:
        cls._check_size(cols, rows)
        self = super().__new__(cls)
        self._input = InputBuffer()
        self._reader_open = True
        self._closed = False
        self._budget = budget
        self._time_budget_s = time_budget_s
        env = user_environment()
        command = list(argv) if argv else [env["SHELL"], "-l"]
        pid, self._fd = pty.fork()
        if pid == 0:
            cls._exec_child(command, env)
        self._child = ChildLifetime(pid)
        try:
            os.set_blocking(self._fd, False)
            self.resize(cols, rows)
        except BaseException:
            self.close()
            raise
        return self

    @property
    def alive(self) -> bool:
        """The PTY still has output to read, possibly after the child exits."""
        return self._reader_open and not self._closed

    @property
    def pid(self) -> int:
        return self._child.pid

    @property
    def exit_code(self) -> int | None:
        return self._child.exit_code

    def pump(self) -> bytes:
        """Drain available output within byte/time bounds, even without viewers."""
        if self._closed:
            self._child.poll()
            return b""
        self._flush_input()
        output = bytearray()
        deadline = time.monotonic() + self._time_budget_s
        while self._reader_open and len(output) < self._budget:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            wait = min(0.002, left) if output else 0.0
            if not select.select([self._fd], [], [], wait)[0]:
                break
            data = self._read(min(64 * 1024, self._budget - len(output)))
            if not data:
                break
            output.extend(data)
        self._child.poll()
        return bytes(output)

    def write(self, data: bytes) -> None:
        if not self.alive or self._child.reaped:
            return
        self._input.append(data)
        self._flush_input()

    def resize(self, cols: int, rows: int) -> None:
        self._check_size(cols, rows)
        if not self._closed:
            fcntl.ioctl(
                self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
            )

    def close(self) -> None:
        """Release the master exactly once, then stop/reap its child."""
        if not self._closed:
            self._closed = True
            self._reader_open = False
            self._input.clear()
            with contextlib.suppress(OSError):
                os.close(self._fd)
        self._child.stop()

    def _read(self, size: int) -> bytes:
        try:
            data = os.read(self._fd, size)
        except BlockingIOError:
            return b""
        except OSError as error:
            if error.errno != errno.EIO:
                raise
            data = b""
        if not data:
            self._reader_open = False
        return data

    def _flush_input(self) -> None:
        if not self._child.reaped:
            try:
                self._input.flush(self._fd)
            except OSError as error:
                if error.errno not in (errno.EIO, errno.EPIPE):
                    raise
                self._input.clear()

    @property
    def budget(self) -> int:
        return self._budget

    @budget.setter
    def budget(self, value: int) -> None:
        self._budget = value

    @property
    def time_budget_s(self) -> float:
        return self._time_budget_s

    @time_budget_s.setter
    def time_budget_s(self, value: float) -> None:
        self._time_budget_s = value

    @staticmethod
    def _check_size(cols: int, rows: int) -> None:
        if not 1 <= cols <= 1024 or not 1 <= rows <= 512:
            raise ValueError("terminal grid is outside the supported bounds")

    @staticmethod
    def _exec_child(argv: list[str], env: dict[str, str]) -> Never:
        try:
            os.execvpe(argv[0], argv, env)  # noqa: S606 -- explicitly requested argv
        except (OSError, ValueError, TypeError) as error:
            with contextlib.suppress(OSError):
                os.write(2, f"exec failed: {error}\n".encode("utf-8", "replace"))
        finally:
            # Even an unexpected exception or audit hook must never unwind
            # into the parent's Python control flow in the forked child.
            os._exit(127)
