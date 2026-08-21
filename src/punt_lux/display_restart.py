"""DisplayRestart — restart the display through its service supervisor.

The display and the Hub share one restart shape: ask the supervisor to
atomically kill-and-respawn (launchctl kickstart -k / systemctl --user
restart), then wait for the process id under the service's
``setproctitle`` name to *change* — the same signal on a first-ever
install (``None`` → new pid) and on an upgrade (old pid → new pid). No
socket peer credential, no pid file, no dependence on state the daemon
does not itself keep current.

Failure is raised as :class:`DisplayRestartError` with a human-worded reason.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux._backends import pgrep_pid
from punt_lux._service_spec import DISPLAY_SPEC, ServiceSpec
from punt_lux.service import (
    DisplayServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DisplayRestart", "DisplayRestartError"]

_POLL_SECONDS = 0.5
_WAIT_SECONDS = 10.0


class DisplayRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class DisplayRestart:
    """Restart the display via its supervisor and wait for the pid to change."""

    _spec: ServiceSpec
    _manager: DisplayServiceManager
    __slots__ = ("_manager", "_spec")

    def __new__(
        cls,
        spec: ServiceSpec | None = None,
        manager: DisplayServiceManager | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec if spec is not None else DISPLAY_SPEC
        self._manager = manager if manager is not None else DisplayServiceManager()
        return self

    def run(self) -> str:
        """Restart the display and return the line describing what came back."""
        before = pgrep_pid(self._spec.process_name)
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise DisplayRestartError(str(exc)) from exc
        return self._await_new_pid(before)

    def _await_new_pid(self, before: int | None) -> str:
        """Wait for a pid that differs from ``before``, and describe it.

        A pid equal to ``before`` is the previous instance still exiting, not
        the respawn — treat it as absent and keep waiting. The first pid
        that satisfies ``pid is not None and pid != before`` witnesses the
        restart; only then is the operation safe to report as complete.
        """
        for _ in self._polls():
            pid = pgrep_pid(self._spec.process_name)
            if pid is not None and pid != before:
                return f"display restarted (pid {pid})"
        msg = f"display did not come back within {_WAIT_SECONDS:.0f}s"
        raise DisplayRestartError(msg)

    @staticmethod
    def _polls() -> Iterator[None]:
        """The bounded poll schedule: sleep, then look, until spent."""
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield
