"""HubRestart — restart luxd through its service supervisor.

Restarting the Hub is one supervisor call, not a signal-and-wait against a
pid file the daemon does not itself keep current. The service manager
(launchd or systemd) already knows luxd's pid, so ask the supervisor to
atomically kill-and-respawn, then wait for the process id under the
service's ``setproctitle`` name to *change* — the same signal on a fresh
install (``None`` → new pid) and on an upgrade (old pid → new pid),
without any dependence on a socket peer credential or pid file.

Failure is raised as :class:`HubRestartError` with the reason already
worded for a human.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux._backends import pgrep_pid
from punt_lux._service_spec import HUB_SPEC, ServiceSpec
from punt_lux.service import (
    HubServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["HubRestart", "HubRestartError"]

# Ten seconds is generous for a local service manager's respawn and short
# enough that a stuck one is reported rather than hung on.
_POLL_SECONDS = 0.5
_WAIT_SECONDS = 10.0


class HubRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class HubRestart:
    """Restart luxd via its supervisor and wait for the pid to change."""

    _spec: ServiceSpec
    _manager: HubServiceManager
    __slots__ = ("_manager", "_spec")

    def __new__(
        cls,
        spec: ServiceSpec | None = None,
        manager: HubServiceManager | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec if spec is not None else HUB_SPEC
        self._manager = manager if manager is not None else HubServiceManager()
        return self

    def run(self) -> str:
        """Restart luxd and return the line describing the Hub that came back."""
        before = pgrep_pid(self._spec.process_name)
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise HubRestartError(str(exc)) from exc
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
                return f"luxd restarted (pid {pid})"
        msg = f"luxd did not come back within {_WAIT_SECONDS:.0f}s"
        raise HubRestartError(msg)

    @staticmethod
    def _polls() -> Iterator[None]:
        """The bounded poll schedule: sleep, then look, until spent.

        Sleeping before the first look is deliberate — the supervisor's
        respawn cannot have completed in the instant after the kickstart
        call returned.
        """
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield
