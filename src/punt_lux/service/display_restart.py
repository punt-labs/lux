"""Restart Display and require stable, PID-matched Hub and socket witnesses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.service import (
    DISPLAY_SPEC,
    DisplayServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
    ServiceSpec,
)
from punt_lux.service._display_readiness import DisplayReadiness
from punt_lux.service._display_restart_attempt import ReadinessError, RestartAttempt
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
        try:
            attempt = RestartAttempt.start(self._spec, _WAIT_SECONDS)
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise DisplayRestartError(str(exc)) from exc
        return self._await_ready(DisplayReadiness(attempt, self._paths))

    def _await_ready(self, readiness: DisplayReadiness) -> str:
        """Require the new process to survive the Hub connection stability window."""
        try:
            for _ in self._polls():
                if (pid := readiness.poll()) is not None:
                    return f"display restarted (pid {pid}) at {self._paths.socket_path}"
            readiness.timeout()
        except ReadinessError as error:
            raise DisplayRestartError(str(error)) from error

    @staticmethod
    def _polls() -> Iterator[None]:
        """Yield the bounded sequence of restart poll delays."""
        return DisplayReadiness.polls(_WAIT_SECONDS, _POLL_SECONDS)
