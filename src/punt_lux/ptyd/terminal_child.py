"""A terminal process group, held unreaped until its last group signal is sent."""

from __future__ import annotations

import os
import signal
import time
from typing import Self


class TerminalChild:
    _pid: int
    _deadline: float | None  # None until group shutdown starts.
    _exit_code: int | None  # None until waitid/waitpid observes exit.
    _reaped: bool

    def __new__(cls, pid: int) -> Self:
        if type(pid) is not int or pid <= 0:
            raise ValueError("child pid must be positive")
        self = super().__new__(cls)
        self._pid = pid
        self._deadline = None
        self._exit_code = None
        self._reaped = False
        return self

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def reaped(self) -> bool:
        return self._reaped

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def stop(self, grace_s: float = 0.3) -> bool:
        if not self._reaped and self._deadline is None:
            self._signal(signal.SIGHUP)
            self._deadline = time.monotonic() + grace_s
        return self.poll()

    def poll(self) -> bool:
        if self._reaped:
            return True
        if self._deadline is None:
            return self._peek_exit() and self.stop()
        if time.monotonic() < self._deadline:
            return False
        self._signal(signal.SIGKILL)
        pid, status_code = os.waitpid(self._pid, os.WNOHANG)
        if pid:
            self._exit_code = os.waitstatus_to_exitcode(status_code)
            self._reaped = True
        return self._reaped

    def _peek_exit(self) -> bool:
        """Record the exit without reaping, so the group stays signallable."""
        status = os.waitid(os.P_PID, self._pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if status is None:
            return False
        code = status.si_status
        self._exit_code = code if status.si_code == os.CLD_EXITED else -code
        return True

    def finish(self) -> None:
        """Bounded cleanup only for construction failure, before ownership transfers."""
        self.stop()
        deadline = time.monotonic() + 0.7
        while not self.poll():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"terminal child {self._pid} could not be reaped")
            time.sleep(0.01)

    def _signal(self, sig: signal.Signals) -> None:
        try:
            os.killpg(self._pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            if not self._exited():
                raise

    def _exited(self) -> bool:
        """Whether the leader has exited, asking the kernel if not yet recorded.

        macOS refuses killpg with EPERM once the group leader is an unreaped
        zombie and no live member remains; that refusal is expected only then.
        """
        return self._exit_code is not None or self._peek_exit()
