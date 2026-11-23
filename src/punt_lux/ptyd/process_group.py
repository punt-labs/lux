"""The process group a terminal leader heads, signalled during shutdown."""

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


class ProcessGroup:
    """Send each shutdown signal to the group; tolerate the refusals exit causes."""

    _pgid: int
    _leader: LeaderStatus

    def __new__(cls, pgid: int, leader: LeaderStatus) -> Self:
        self = super().__new__(cls)
        self._pgid = pgid
        self._leader = leader
        return self

    def signal(self, sig: signal.Signals) -> None:
        """Signal every member of the group.

        A missing group and a refusal after the leader exited are routine and
        never stop a later signal: neither proves no member remains.

        Raises:
            PermissionError: the kernel refused the signal while the leader
                was still running.
        """
        try:
            os.killpg(self._pgid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            # macOS refuses killpg once the leader is an unreaped zombie, even
            # with no member left to receive it.
            if not self._leader_exit_visible():
                raise
            logger.debug(
                "process group %d: killpg(%s) refused with EPERM after the "
                "leader exited (exit code %s)",
                self._pgid,
                sig.name,
                self._leader.exit_code,
            )

    def _leader_exit_visible(self) -> bool:
        """Wait briefly for a dying leader's exit to show to waitid.

        The kernel refuses a group signal (EPERM) a few milliseconds before
        waitid reports the exit of a leader it is tearing down.
        """
        deadline = time.monotonic() + _EXIT_VISIBLE_S
        while not self._leader.exited():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.002)
        return True
