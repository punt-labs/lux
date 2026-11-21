"""A terminal process group, held unreaped until its last group signal is sent."""

from __future__ import annotations

import logging
import os
import signal
import time
from typing import Self

from punt_lux.ptyd.leader_status import LeaderStatus

logger = logging.getLogger(__name__)

# How long a refused group signal may wait for the leader's exit to show.
_EXIT_VISIBLE_S = 0.1


class TerminalChild:
    _pid: int
    _deadline: float | None  # None until group shutdown starts.
    _status: LeaderStatus

    def __new__(cls, pid: int) -> Self:
        if type(pid) is not int or pid <= 0:
            raise ValueError("child pid must be positive")
        self = super().__new__(cls)
        self._pid = pid
        self._deadline = None
        self._status = LeaderStatus(pid)
        return self

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def reaped(self) -> bool:
        return self._status.reaped

    @property
    def exit_code(self) -> int | None:
        return self._status.exit_code

    def stop(self, grace_s: float = 0.3) -> bool:
        if not self._status.reaped and self._deadline is None:
            self._signal(signal.SIGHUP)
            self._deadline = time.monotonic() + grace_s
        return self.poll()

    def poll(self) -> bool:
        if self._status.reaped:
            return True
        if self._deadline is None:
            return self._status.exited() and self.stop()
        if time.monotonic() < self._deadline:
            return False
        self._signal(signal.SIGKILL)
        return self._status.reap()

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
            # macOS refuses killpg once the leader is an unreaped zombie. That
            # is all that is checked: a live member under another euid is not
            # ruled out, so each tolerated refusal is logged.
            if not self._exit_becomes_visible():
                raise
            logger.warning(
                "terminal child %d: killpg(%s) refused with EPERM after the "
                "leader exited (exit code %s); group members may remain",
                self._pid,
                sig.name,
                self._status.exit_code,
            )

    def _exit_becomes_visible(self) -> bool:
        """Wait briefly for a dying leader's exit to show to waitid.

        The kernel refuses a group signal (EPERM) a few milliseconds before
        waitid reports the exit of a leader it is tearing down.
        """
        deadline = time.monotonic() + _EXIT_VISIBLE_S
        while not self._status.exited():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.002)
        return True
