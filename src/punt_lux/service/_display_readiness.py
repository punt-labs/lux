"""Observe one Display generation through startup and a stability interval."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Self

from punt_lux.service._display_stability import DisplayStability
from punt_lux.service._readiness_probe import ReadinessProbe
from punt_lux.service._restart_readiness import RestartReadiness

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.service import ServiceSpec
    from punt_lux.service.display_paths import DisplayPaths

_STABILITY_SECONDS = 3.0
_PROBE_SECONDS = 0.5


class DisplayReadinessError(RuntimeError):
    """A Display never became ready or lost its observed generation."""


class DisplayReadiness:
    """Bound startup and require continuous observations of the same Display."""

    __slots__ = (
        "_deadline",
        "_last_error",
        "_paths",
        "_pending",
        "_pid",
        "_spec",
        "_stability",
        "_started_at",
        "_wait",
    )
    _spec: ServiceSpec
    _paths: DisplayPaths
    _wait: float
    _deadline: float
    _pid: int | None
    _stability: DisplayStability
    _started_at: float
    _pending: str
    _last_error: str

    def __new__(
        cls,
        spec: ServiceSpec,
        paths: DisplayPaths,
        wait: float,
        started_at: float | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._paths = paths
        self._wait = wait
        self._deadline = time.monotonic() + wait
        self._pid = None
        self._stability = DisplayStability(_STABILITY_SECONDS)
        self._started_at = time.time() if started_at is None else started_at
        self._pending = "never connected to Hub with the new PID"
        self._last_error = ""
        return self

    @staticmethod
    def polls(wait: float, interval: float) -> Iterator[None]:
        """Sleep only inside the total deadline, including time spent probing."""
        deadline = time.monotonic() + wait
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(interval, remaining))
            if time.monotonic() < deadline:
                yield

    def observe(self, pid: int | None, before: int | None) -> bool:
        """Accept only a stable Hub reply and local socket from the new process."""
        self.remaining()
        candidate = self._candidate(pid, before)
        if candidate is None:
            return False
        if not self._local_alive(candidate):
            return self._disconnected()
        sent_at = time.monotonic()
        try:
            connected = ReadinessProbe.connected(
                candidate, min(_PROBE_SECONDS, self.remaining())
            )
        except ConnectionError as error:
            self._last_error = f"; last Hub transport error: {error}"
            connected = None
        observed_at = time.monotonic()
        if not self._local_alive(candidate):
            return self._disconnected()
        return self._stability.observe(connected, (sent_at, observed_at))

    def _candidate(self, pid: int | None, before: int | None) -> int | None:
        if self._pid is not None and pid != self._pid:
            self._lost("exited")
        self._pid = pid if pid != before else None
        return self._pid

    def remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.timeout()
        return remaining

    def timeout(self) -> NoReturn:
        """Explain which startup witness never became stable."""
        reason = self._pending
        if self._stability.started:
            reason = "did not complete the Hub connection stability window"
        self._fail(
            f"display did not come back within {self._wait:g}s: "
            f"{reason}{self._last_error}"
        )

    def _local_alive(self, pid: int) -> bool:
        connected = ReadinessProbe(self._paths).local(pid, self.remaining())
        self.remaining()
        if not connected:
            self._pending = (
                f"live display pid {pid} has no live owned local socket "
                f"at {self._paths.socket_path}"
            )
        return connected

    def _disconnected(self) -> bool:
        if self._stability.started:
            self._lost("disconnected from Hub or lost its socket")
        return False

    def _lost(self, reason: str) -> NoReturn:
        phase = self._stability.phase(time.monotonic())
        self._fail(f"display pid {self._pid} {reason} {phase}")

    def _fail(self, message: str) -> NoReturn:
        message += self._stderr_tail(self._started_at)
        RestartReadiness.failure(self._spec, message)
        raise DisplayReadinessError(message)

    @staticmethod
    def _stderr_tail(started_at: float = 0) -> str:
        path = Path.home() / ".punt-labs/lux/logs/luxd-display-stderr.log"
        try:
            with path.open("rb") as stream:
                mtime = os.fstat(stream.fileno()).st_mtime
                if mtime < started_at:
                    return (
                        f"\nDisplay stderr omitted: mtime {mtime:.6f} "
                        f"predates restart start {started_at:.6f}."
                    )
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 4096))
                tail = stream.read(4096).decode("utf-8", errors="replace")
        except OSError:
            return ""
        lines = tail.splitlines()[-12:]
        if not lines:
            return ""
        return (
            f"\nDisplay stderr (mtime {mtime:.6f}, "
            "last 12 lines, at most 4096 bytes):\n" + "\n".join(lines)
        )
