"""Observe one Display generation through startup and a stability interval."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NoReturn, Self

from punt_lux.service._display_restart_scope import DisplayRestartScope
from punt_lux.service._display_stability import DisplayStability

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.service._display_restart_attempt import RestartAttempt
    from punt_lux.service.display_paths import DisplayPaths

_STABILITY_SECONDS = 3.0


class DisplayReadiness:
    """Bound startup and require continuous observations of the same Display."""

    __slots__ = ("_pid", "_scope", "_stability")
    _scope: DisplayRestartScope
    _pid: int | None
    _stability: DisplayStability

    def __new__(cls, attempt: RestartAttempt, paths: DisplayPaths) -> Self:
        self = super().__new__(cls)
        self._scope = DisplayRestartScope(attempt, paths)
        self._pid = None
        self._stability = DisplayStability(_STABILITY_SECONDS)
        return self

    @staticmethod
    def polls(wait: float, interval: float) -> Iterator[None]:
        """Sleep only inside the total deadline, including time spent probing."""
        deadline = time.monotonic() + wait
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(interval, remaining))
            if time.monotonic() < deadline:
                yield

    def pid(self) -> int | None:
        """Read the process identity without exceeding this attempt's deadline."""
        return self._scope.pid((self._pid, self._stability.started))

    def observe(self, pid: int | None) -> bool:
        """Accept only a stable Hub reply and local socket from the new process."""
        self.remaining()
        candidate = self._candidate(pid)
        if candidate is None:
            return False
        if not self._scope.local(candidate, stabilizing=self._stability.started):
            return self._disconnected()
        sent_at = time.monotonic()
        connected = self._scope.connected(
            candidate, stabilizing=self._stability.started
        )
        observed_at = time.monotonic()
        if not self._scope.local(candidate, stabilizing=self._stability.started):
            return self._disconnected()
        return self._stability.observe(connected, (sent_at, observed_at))

    def _candidate(self, pid: int | None) -> int | None:
        if self._pid is not None and pid != self._pid:
            self._lost("exited")
        self._pid = pid if pid != self._scope.before else None
        return self._pid

    def remaining(self) -> float:
        return self._scope.remaining(stabilizing=self._stability.started)

    def timeout(self) -> NoReturn:
        """Explain which startup witness never became stable."""
        self._scope.timeout(stabilizing=self._stability.started)

    def _disconnected(self) -> bool:
        if self._stability.started:
            self._lost("disconnected from Hub or lost its socket")
        return False

    def _lost(self, reason: str) -> NoReturn:
        phase = self._stability.phase(time.monotonic())
        self._scope.fail(f"display pid {self._pid} {reason} {phase}")
