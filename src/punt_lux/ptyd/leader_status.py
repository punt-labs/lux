"""Exit status of a terminal group leader, observed without losing the group."""

from __future__ import annotations

import logging
import os
from typing import Self

logger = logging.getLogger(__name__)


class LeaderStatus:
    """Peek at, then reap, one child; an already-reaped child counts as reaped."""

    _pid: int
    _exit_code: int | None
    _reaped: bool

    def __new__(cls, pid: int) -> Self:
        self = super().__new__(cls)
        self._pid = pid
        self._exit_code = None
        self._reaped = False
        return self

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def reaped(self) -> bool:
        return self._reaped

    def exited(self) -> bool:
        """Record the exit without reaping, so the group stays signallable."""
        if self._exit_code is not None or self._reaped:
            return True
        try:
            status = os.waitid(
                os.P_PID, self._pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
            )
        except ChildProcessError:
            return self._gone()
        if status is None:
            return False
        code = status.si_status
        self._exit_code = code if status.si_code == os.CLD_EXITED else -code
        return True

    def reap(self) -> bool:
        """Reap with WNOHANG; return whether the child is now reaped."""
        if self._reaped:
            return True
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            return self._gone()
        if pid:
            self._exit_code = os.waitstatus_to_exitcode(status)
            self._reaped = True
        return self._reaped

    def _gone(self) -> bool:
        logger.warning("terminal child %d was already reaped elsewhere", self._pid)
        self._reaped = True
        return True
