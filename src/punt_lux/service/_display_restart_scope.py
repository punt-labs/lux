"""The process/I/O budget and diagnostics belonging to one Display restart."""

from __future__ import annotations

import http.client
import os
from collections.abc import Callable
from dataclasses import dataclass
from subprocess import TimeoutExpired
from typing import TYPE_CHECKING, NoReturn, Self

from punt_lux.kernel.home_paths import LuxHome
from punt_lux.service._display_restart_attempt import ReadinessError
from punt_lux.service._hub_display_probe import HubDisplayProbe
from punt_lux.service._readiness_http import ProbeDeadline
from punt_lux.service._readiness_probe import ReadinessProbe
from punt_lux.service._restart_readiness import RestartReadiness
from punt_service import _backends

if TYPE_CHECKING:
    from punt_lux.service._display_restart_attempt import RestartAttempt
    from punt_lux.service.display_paths import DisplayPaths

_PROBE_SECONDS = 0.5
type _Observe = Callable[[str | None, tuple[float, float]], bool]  # None: reset window.


@dataclass(frozen=True, slots=True)
class _ProbeConnected:
    hub_connection_id: str

    def observe(self, observer: _Observe, interval: tuple[float, float]) -> bool:
        return observer(self.hub_connection_id, interval)


@dataclass(frozen=True, slots=True)
class _ProbePending:
    reason: str

    def observe(self, observer: _Observe, interval: tuple[float, float]) -> bool:
        return observer(None, interval)


class DisplayRestartScope:
    """Spend one deadline and explain only witnesses seen in this attempt."""

    _attempt: RestartAttempt
    _paths: DisplayPaths
    _budget: ProbeDeadline
    _probe: ReadinessProbe
    _pending: str
    _last_error: str

    def __new__(cls, attempt: RestartAttempt, paths: DisplayPaths) -> Self:
        self = super().__new__(cls)
        self._attempt = attempt
        self._paths = paths
        self._budget = ProbeDeadline(attempt.wait)
        self._probe = ReadinessProbe(paths)
        self._pending = "never connected to Hub with the new PID"
        self._last_error = ""
        return self

    @property
    def before(self) -> int | None:
        return self._attempt.before

    def remaining(self, *, stabilizing: bool) -> float:
        try:
            return self._budget.remaining()
        except TimeoutError:
            self.timeout(stabilizing=stabilizing)

    def pid(self, observation: tuple[int | None, bool]) -> int | None:
        """Start a process query only when its entire fixed timeout fits."""
        candidate, stabilizing = observation
        if self.remaining(stabilizing=stabilizing) < _backends.PGREP_TIMEOUT:
            return candidate
        try:
            return _backends.pgrep_pid(self._attempt.spec.process_name)
        except TimeoutExpired as error:
            self._last_error = f"; last PID lookup error: {error}"
            raise

    def local(self, pid: int, *, stabilizing: bool) -> bool:
        connected = self._probe.local(pid, self.remaining(stabilizing=stabilizing))
        self.remaining(stabilizing=stabilizing)
        self._pending = "never connected to Hub with the new PID"
        if not connected:
            self._pending = (
                f"live display pid {pid} has no live owned local socket "
                f"at {self._paths.socket_path}"
            )
        return connected

    def connected(
        self, pid: int, *, stabilizing: bool
    ) -> _ProbeConnected | _ProbePending:
        try:
            identity = HubDisplayProbe(
                pid, min(_PROBE_SECONDS, self.remaining(stabilizing=stabilizing))
            ).connected()
            return (
                _ProbeConnected(identity) if identity else _ProbePending(self._pending)
            )
        except (OSError, http.client.HTTPException, ValueError) as error:
            pending = _ProbePending(f"last Hub transport error: {error}")
            self._last_error = f"; {pending.reason}"
            return pending

    def timeout(self, *, stabilizing: bool) -> NoReturn:
        reason = self._pending
        if stabilizing:
            reason = "did not complete the Hub connection stability window"
        self.fail(
            f"display did not come back within {self._attempt.wait:g}s: "
            f"{reason}{self._last_error}"
        )

    def fail(self, message: str) -> NoReturn:
        message += self.stderr_tail()
        RestartReadiness.failure(self._attempt.spec, message)
        raise ReadinessError(message)

    def stderr_tail(self) -> str:
        """Attach a bounded tail only when the captured file is fresh."""
        try:
            with LuxHome.resolve().display_stderr.open("rb") as stream:
                mtime = os.fstat(stream.fileno()).st_mtime
                if mtime < self._attempt.started_at:
                    return (
                        f"\nDisplay stderr omitted: mtime {mtime:.6f} "
                        f"predates restart start {self._attempt.started_at:.6f}."
                    )
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 4096))
                tail = stream.read(4096).decode("utf-8", errors="replace")
        except (OSError, RuntimeError):
            return ""
        lines = tail.splitlines()[-12:]
        if not lines:
            return ""
        return (
            f"\nDisplay stderr (mtime {mtime:.6f}, "
            "last 12 lines, at most 4096 bytes):\n" + "\n".join(lines)
        )
