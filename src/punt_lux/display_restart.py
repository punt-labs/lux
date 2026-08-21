"""DisplayRestart — term the display and wait for its supervisor to bring it back.

Restarting the display mirrors ``HubRestart``'s two-phase wait: SIGTERM, watch
the old owner go, then watch a live socket come back under a different pid.
Waiting for the new pid is what makes the operation honest — returning as soon
as the old one died would report a restart that had not happened yet.

Unlike the Hub (a port, no socket peer credential available), the display is
reached over a Unix socket, so the pid to signal is resolved via
``DisplayPaths.peer_pid`` — the kernel's live peer credential — rather than
trusted from the pid file: a pid file can be stale or, worse, reused by an
unrelated process, and signalling on faith is not safe here.

Failure is raised as :class:`DisplayRestartError` with a human-worded reason.
"""

from __future__ import annotations

import os
import signal
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.paths import DisplayPaths

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DisplayRestart", "DisplayRestartError"]

_POLL_SECONDS = 0.5
_WAIT_SECONDS = 10.0


class DisplayRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class DisplayRestart:
    """Term the display and wait for the supervisor to respawn it on a new pid."""

    _paths: DisplayPaths
    __slots__ = ("_paths",)

    def __new__(cls, paths: DisplayPaths | None = None) -> Self:
        self = super().__new__(cls)
        self._paths = paths if paths is not None else DisplayPaths()
        return self

    def run(self) -> str:
        """Restart the display and return the line describing what came back."""
        old_pid = self._term()
        self._await_exit(old_pid)
        return self._await_respawn(old_pid)

    def _term(self) -> int:
        """Send SIGTERM to the socket's live owner and return its pid.

        Resolved via the kernel peer credential, not the pid file: a pid file
        can be stale or belong to an unrelated process that has since reused
        the pid, and signalling on that faith is not safe.
        """
        pid = self._paths.peer_pid()
        if pid is None:
            msg = f"could not resolve display's live pid at {self._paths.socket_path}"
            raise DisplayRestartError(msg)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            msg = f"could not signal display (pid {pid}): {exc}"
            raise DisplayRestartError(msg) from exc
        return pid

    def _await_exit(self, pid: int) -> None:
        """Wait for the termed process to go, or raise once the bound passes."""
        for _ in self._polls():
            if not self._alive(pid) or not self._paths.is_running():
                return
        msg = f"display (pid {pid}) did not stop within {_WAIT_SECONDS:.0f}s"
        raise DisplayRestartError(msg)

    def _await_respawn(self, old_pid: int) -> str:
        """Wait for a different live pid to own the socket, and describe it."""
        for _ in self._polls():
            pid = self._live_pid()
            if pid is None or pid == old_pid:
                continue
            return f"display restarted (pid {pid}) at {self._paths.socket_path}"
        msg = f"display did not restart within {_WAIT_SECONDS:.0f}s"
        raise DisplayRestartError(msg)

    def _live_pid(self) -> int | None:
        """The socket's live owner pid, or ``None`` while there is not one yet.

        Resolved via the kernel peer credential, same as ``_term`` — the pid
        file is not consulted, so a stale file can never be mistaken for the
        fresh respawn this wait is looking for.
        """
        if not self._paths.is_running():
            return None
        return self._paths.peer_pid()

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
        """The bounded poll schedule both waits share."""
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield
