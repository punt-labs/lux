"""Nonblocking child status and bounded termination, independent of PTY IO."""

from __future__ import annotations

import os
import signal
import time
from typing import Self


class ChildLifetime:
    """Own the right to signal/reap one child; never signal a reaped PID."""

    _pid: int
    _reaped: bool
    _exit_code: int | None

    def __new__(cls, pid: int) -> Self:
        if type(pid) is not int or pid <= 0:
            raise ValueError("child pid must be positive")
        self = super().__new__(cls)
        self._pid = pid
        self._reaped = False
        self._exit_code = None
        return self

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def reaped(self) -> bool:
        return self._reaped

    @property
    def exit_code(self) -> int | None:
        """None before status is known; signals are negative, as in subprocess."""
        return self._exit_code

    def poll(self) -> bool:
        """Observe and reap an exited child using WNOHANG only."""
        if self._reaped:
            return True
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            self._reaped = True
            return True
        if pid:
            self._exit_code = os.waitstatus_to_exitcode(status)
            self._reaped = True
        return self._reaped

    def stop(self, grace_s: float = 0.3) -> None:
        """Hang up, then kill if needed; no blocking waitpid or PID reuse."""
        if self.poll():
            return
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.kill(self._pid, sig)
            except ProcessLookupError:
                self.poll()
                return
            if self._wait_until(time.monotonic() + grace_s):
                return
        # A pathological kernel delay remains observable rather than hidden.
        if not self._reaped:
            raise TimeoutError(f"child {self._pid} did not exit after SIGKILL")

    def _wait_until(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if self.poll():
                return True
            time.sleep(0.01)
        return self.poll()
