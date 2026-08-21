"""DisplayRestart — restart the display through its service supervisor.

The display and the Hub share one restart shape: ask the supervisor to
atomically kill-and-respawn (launchctl kickstart -k / systemctl --user
restart), then wait for two independent witnesses — a new pid under the
service's ``setproctitle`` name AND a live socket that accepts a
connection. Requiring both closes the gap between "process exists" and
"socket is accepting": setproctitle fires early in display startup, well
before the socket is bound.

Failure is raised as :class:`DisplayRestartError` with a human-worded reason.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux._backends import pgrep_pid
from punt_lux._service_spec import DISPLAY_SPEC, ServiceSpec
from punt_lux.paths import DisplayPaths
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
    """Restart the display via its supervisor and wait for pid + socket."""

    _spec: ServiceSpec
    _manager: DisplayServiceManager
    _paths: DisplayPaths
    __slots__ = ("_manager", "_paths", "_spec")

    def __new__(
        cls,
        spec: ServiceSpec | None = None,
        manager: DisplayServiceManager | None = None,
        paths: DisplayPaths | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec if spec is not None else DISPLAY_SPEC
        self._manager = manager if manager is not None else DisplayServiceManager()
        self._paths = paths if paths is not None else DisplayPaths()
        return self

    def run(self) -> str:
        """Restart the display and return the line describing what came back."""
        before = pgrep_pid(self._spec.process_name)
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise DisplayRestartError(str(exc)) from exc
        return self._await_ready(before)

    def _await_ready(self, before: int | None) -> str:
        """Wait for a new pid AND a socket that answers, and describe it.

        setproctitle fires at the top of the display's ``run`` method,
        before the socket is bound and accepting. Requiring
        ``paths.is_running()`` (an AF_UNIX connect probe) alongside the
        pid change closes the gap between "process exists" and
        "clients can connect".
        """
        for _ in self._polls():
            pid = pgrep_pid(self._spec.process_name)
            if pid is None or pid == before:
                continue
            if not self._paths.is_running():
                continue
            return f"display restarted (pid {pid}) at {self._paths.socket_path}"
        msg = f"display did not come back within {_WAIT_SECONDS:.0f}s"
        raise DisplayRestartError(msg)

    @staticmethod
    def _polls() -> Iterator[None]:
        """The bounded poll schedule: sleep, then look, until spent."""
        for _ in range(int(_WAIT_SECONDS / _POLL_SECONDS)):
            time.sleep(_POLL_SECONDS)
            yield
