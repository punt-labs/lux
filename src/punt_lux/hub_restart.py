"""HubRestart — restart luxd through its service supervisor.

Restarting the Hub is one supervisor call, not a signal-and-wait against a
pid file the daemon does not itself keep current. The service manager
(launchd or systemd) already knows luxd's pid, so the correct primitive is
to ask the supervisor to atomically kill-and-respawn — then wait for the
port to answer again so the return line is honest about a Hub that has
actually come back.

Failure is raised as :class:`HubRestartError` with the reason already
worded for a human.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.hub_paths import HubPaths
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
    """Restart luxd via its supervisor and wait for the port to answer again."""

    _paths: HubPaths
    _manager: HubServiceManager
    __slots__ = ("_manager", "_paths")

    def __new__(
        cls,
        paths: HubPaths | None = None,
        manager: HubServiceManager | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._paths = paths if paths is not None else HubPaths()
        self._manager = manager if manager is not None else HubServiceManager()
        return self

    def run(self) -> str:
        """Restart luxd and return the line describing the Hub that came back."""
        try:
            self._manager.restart()
        except (ServiceActionFailedError, ServiceNotInstalledError) as exc:
            raise HubRestartError(str(exc)) from exc
        return self._await_live()

    def _await_live(self) -> str:
        """Wait for the supervisor's respawn to expose a live Hub, and describe it.

        Liveness is the same check ``lux hub status`` uses — the pid file
        plus the port file. It is polled here, never signalled against; the
        broken pre-supervisor path signalled a pid it had read from a file
        that could be absent or stale, and getting the pid out of the
        restart entirely is what fixes that.
        """
        for _ in self._polls():
            if not self._paths.is_running():
                continue
            port = self._paths.read_port()
            where = f"port {port}" if port is not None else "port file not yet written"
            return f"luxd restarted ({where})"
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
