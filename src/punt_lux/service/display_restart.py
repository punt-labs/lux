"""Restart Display and require stable, PID-matched Hub and socket witnesses."""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.service import (
    DISPLAY_SPEC,
    DisplayServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
    ServiceSpec,
)
from punt_lux.service._backends import pgrep_pid
from punt_lux.service._display_readiness import DisplayReadiness, DisplayReadinessError
from punt_lux.service.display_paths import DisplayPaths

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["DisplayRestart", "DisplayRestartError"]

# Thirty seconds spans an ImGui cold start: loading imgui-bundle
# (~66 MB), building the GL context, and creating the window measurably
# outlasts ten seconds on a warm laptop and much more so on a loaded CI
# runner.
_POLL_SECONDS = 0.5
_WAIT_SECONDS = 30.0


class DisplayRestartError(RuntimeError):
    """A restart could not be completed; the message names what went wrong."""


@final
class DisplayRestart:
    """Restart the display and wait for a stable Hub-connected generation."""

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
        """Configure the dependencies used to restart the display."""
        self = super().__new__(cls)
        self._spec = spec if spec is not None else DISPLAY_SPEC
        self._manager = manager if manager is not None else DisplayServiceManager()
        self._paths = paths if paths is not None else DisplayPaths()
        return self

    def run(self) -> str:
        """Restart the display and return the line describing what came back."""
        started_at = time.time()
        before = pgrep_pid(self._spec.process_name)
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise DisplayRestartError(str(exc)) from exc
        return self._await_ready(before, started_at)

    def _await_ready(self, before: int | None, started_at: float | None = None) -> str:
        """Require the new process to survive the Hub connection stability window."""
        readiness = DisplayReadiness(self._spec, self._paths, _WAIT_SECONDS, started_at)
        try:
            for _ in self._polls():
                try:
                    pid = pgrep_pid(
                        self._spec.process_name, timeout=readiness.remaining()
                    )
                except subprocess.TimeoutExpired:
                    readiness.timeout()
                if readiness.observe(pid, before):
                    return f"display restarted (pid {pid}) at {self._paths.socket_path}"
            readiness.timeout()
        except DisplayReadinessError as error:
            raise DisplayRestartError(str(error)) from error

    @staticmethod
    def _polls() -> Iterator[None]:
        """Yield the bounded sequence of restart poll delays."""
        return DisplayReadiness.polls(_WAIT_SECONDS, _POLL_SECONDS)
