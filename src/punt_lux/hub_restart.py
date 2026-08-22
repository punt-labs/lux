"""HubRestart — restart luxd through its service supervisor.

Restarting the Hub is one supervisor call, not a signal-and-wait against a
pid file the daemon does not itself keep current. The service manager
(launchd or systemd) already knows luxd's pid, so ask the supervisor to
atomically kill-and-respawn, then wait for two independent witnesses
before declaring the restart complete: the process id under the
service's ``setproctitle`` name has *changed* (the new instance is
running) and ``HubPaths.is_running()`` returns true (uvicorn has bound,
because luxd only writes its pid file after ``_startup_with_port_file``
returns). Requiring both closes the gap between "process exists" and
"port is up" — setproctitle is called before uvicorn binds, so pgrep
alone would say restarted while ``curl :8430`` still refuses.

Failure is raised as :class:`HubRestartError` with the reason already
worded for a human.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux._backends import pgrep_pid
from punt_lux._service_spec import HUB_SPEC, ServiceSpec
from punt_lux.hub_paths import HubPaths
from punt_lux.service import (
    HubServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["HubRestart", "HubRestartError"]

# Thirty seconds spans a cold start on a fresh install: importing the
# ``[display]`` extras (imgui-bundle at ~66 MB, numpy, Pillow) plus the
# service manager's respawn and uvicorn's port bind routinely takes
# 15-25s on a warm laptop and longer on a loaded CI runner. Ten seconds
# was tight enough to false-alarm during ``install.sh``.
_POLL_SECONDS = 0.5
_WAIT_SECONDS = 30.0


class HubRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class HubRestart:
    """Restart luxd via its supervisor and wait for both pid and port."""

    _spec: ServiceSpec
    _manager: HubServiceManager
    _paths: HubPaths
    __slots__ = ("_manager", "_paths", "_spec")

    def __new__(
        cls,
        spec: ServiceSpec | None = None,
        manager: HubServiceManager | None = None,
        paths: HubPaths | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec if spec is not None else HUB_SPEC
        self._manager = manager if manager is not None else HubServiceManager()
        self._paths = paths if paths is not None else HubPaths()
        return self

    def run(self) -> str:
        """Restart luxd and return the line describing the Hub that came back."""
        before = pgrep_pid(self._spec.process_name)
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise HubRestartError(str(exc)) from exc
        return self._await_ready(before)

    def _await_ready(self, before: int | None) -> str:
        """Wait for a new pid AND a live port, and describe it.

        A pid alone is not enough — luxd calls ``set_process_title`` at
        the top of ``main`` before uvicorn binds, so pgrep can see the new
        pid while the TCP port is still down. The pid file, written only
        after ``_startup_with_port_file`` completes, is what witnesses the
        port is actually up. Requiring both means a returned "restarted"
        line is safe to hand to the next ``curl :8430``.
        """
        for _ in self._polls():
            pid = pgrep_pid(self._spec.process_name)
            if pid is None or pid == before:
                continue
            if not self._paths.is_running():
                continue
            port = self._paths.read_port()
            where = f"port {port}" if port is not None else "port file not yet written"
            return f"luxd restarted (pid {pid}, {where})"
        msg = f"luxd did not come back within {_WAIT_SECONDS:.0f}s"
        raise HubRestartError(msg)

    @staticmethod
    def _polls() -> Iterator[None]:
        """The bounded poll schedule: sleep, then look, until spent."""
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield
