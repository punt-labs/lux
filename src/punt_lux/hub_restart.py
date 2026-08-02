"""HubRestart — stop luxd and wait for its service manager to bring it back.

Restarting the Hub is not a signal, it is a handshake with launchd or systemd:
send the term, watch the old process go, then watch a *different* pid appear with
a port behind it. Waiting for the new pid is what makes the operation honest —
returning as soon as the old one died would report a restart that had not happened
yet, and the next command would find no Hub.

The steps and their bounds live here rather than in the CLI so the CLI stays what
it should be: parse, call, print. Failure is raised as :class:`HubRestartError`
with the reason already worded for a human.
"""

from __future__ import annotations

import os
import signal
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.hub_paths import HubPaths

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ["HubRestart", "HubRestartError"]

# Each wait polls at this interval up to this bound. Ten seconds is generous for
# a local service manager's respawn and short enough that a stuck one is reported
# rather than hung on.
_POLL_SECONDS = 0.5
_WAIT_SECONDS = 10.0


class HubRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class HubRestart:
    """Term luxd and wait for the service manager to respawn it on a new pid."""

    _paths: HubPaths
    __slots__ = ("_paths",)

    # ``paths`` absent means "the real Hub's paths" — resolved per instance rather
    # than bound once at import, so a caller (a test) can restart against its own
    # state directory without the default reaching into someone's home.
    def __new__(cls, paths: HubPaths | None = None) -> Self:
        self = super().__new__(cls)
        self._paths = paths if paths is not None else HubPaths()
        return self

    def run(self) -> str:
        """Restart luxd and return the line describing the Hub that came back."""
        old_pid = self._term()
        self._await_exit(old_pid)
        return self._await_respawn(old_pid)

    def _term(self) -> int:
        """Send SIGTERM to the recorded pid and return it, or say why it failed."""
        try:
            pid = int(self._pid_path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError) as exc:
            msg = f"could not signal luxd: {exc}"
            raise HubRestartError(msg) from exc
        return pid

    def _await_exit(self, pid: int) -> None:
        """Wait for the termed process to go, or raise once the bound passes."""
        for _ in self._polls():
            if not self._alive(pid):
                return
        msg = f"luxd (pid {pid}) did not stop within {_WAIT_SECONDS:.0f}s"
        raise HubRestartError(msg)

    def _await_respawn(self, old_pid: int) -> str:
        """Wait for a *different* live pid to own the Hub, and describe it.

        A pid equal to the old one is the file not yet rewritten, not a restart,
        so it keeps waiting. A live new pid whose port file has not landed yet is
        still a restart, and is reported as such rather than failed.
        """
        for _ in self._polls():
            pid = self._live_pid()
            if pid is None or pid == old_pid:
                continue
            port = self._paths.read_port()
            where = f"port {port}" if port is not None else "port file not yet written"
            return f"luxd restarted (pid {pid}, {where})"
        msg = f"luxd did not restart within {_WAIT_SECONDS:.0f}s"
        raise HubRestartError(msg)

    def _live_pid(self) -> int | None:
        """The pid of a running Hub, or ``None`` while there is not one yet.

        Absence is the expected state mid-restart — the service manager has not
        respawned, or the pid file is being rewritten — so the caller keeps
        waiting rather than treating it as a failure.
        """
        if not self._paths.is_running():
            return None
        try:
            return int(self._pid_path.read_text().strip())
        except (ValueError, OSError):
            return None

    @staticmethod
    def _alive(pid: int) -> bool:
        """Whether ``pid`` still exists; an unreadable process counts as gone."""
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True

    @staticmethod
    def _polls() -> Iterator[None]:
        """The bounded poll schedule both waits share: sleep, then look, until spent.

        Sleeping before the first look is deliberate — neither the process's exit
        nor the manager's respawn can have happened in the instant after the term.
        """
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield

    @property
    def _pid_path(self) -> Path:
        return self._paths.pid_path
