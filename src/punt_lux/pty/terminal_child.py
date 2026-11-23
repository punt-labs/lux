"""A terminal process group, held unreaped until its last group signal is sent."""

from __future__ import annotations

import signal
import time
from typing import Self

from punt_lux.pty.leader_status import LeaderStatus
from punt_lux.pty.process_group import ProcessGroup


class TerminalChild:
    _pid: int
    _deadline: float | None  # None until group shutdown starts.
    _status: LeaderStatus
    _group: ProcessGroup

    def __new__(cls, pid: int) -> Self:
        if type(pid) is not int or pid <= 0:
            raise ValueError("child pid must be positive")
        self = super().__new__(cls)
        self._pid = pid
        self._deadline = None
        self._status = LeaderStatus(pid)
        self._group = ProcessGroup(pid, self._status)
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
            self._group.signal(signal.SIGHUP)
            self._deadline = time.monotonic() + grace_s
        return self.poll()

    def poll(self) -> bool:
        if self._status.reaped:
            return True
        if self._deadline is None:
            return self._status.exited() and self.stop()
        if time.monotonic() < self._deadline:
            return False
        self._group.signal(signal.SIGKILL)
        return self._status.reap()

    def finish(self) -> None:
        """Bounded cleanup only for construction failure, before ownership transfers."""
        self.stop()
        deadline = time.monotonic() + 0.7
        while not self.poll():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"terminal child {self._pid} could not be reaped")
            time.sleep(0.01)
