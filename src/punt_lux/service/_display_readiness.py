"""Observe one Display generation through startup and a stability interval."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Self

from punt_lux.service._hub_display_probe import HubDisplayProbe
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

    __slots__ = ("_connected_at", "_deadline", "_paths", "_pid", "_spec", "_wait")
    _spec: ServiceSpec
    _paths: DisplayPaths
    _wait: float
    _deadline: float
    _pid: int | None
    _connected_at: float | None

    def __new__(cls, spec: ServiceSpec, paths: DisplayPaths, wait: float) -> Self:
        self = super().__new__(cls)
        self._spec = spec
        self._paths = paths
        self._wait = wait
        self._deadline = time.monotonic() + wait
        self._pid = None
        self._connected_at = None
        return self

    @staticmethod
    def polls(wait: float, interval: float) -> Iterator[None]:
        """Sleep only inside the total deadline, including time spent probing."""
        deadline = time.monotonic() + wait
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(interval, remaining))
            yield

    def observe(self, pid: int | None, before: int | None) -> bool:
        """Accept only a stable Hub reply and local socket from the new process."""
        self._remaining()
        candidate = self._candidate(pid, before)
        if candidate is None:
            return False
        if not self._local_alive(candidate):
            return self._disconnected()
        try:
            connected = HubDisplayProbe.connected(
                candidate, min(_PROBE_SECONDS, self._remaining())
            )
        except ConnectionError as error:
            self._fail(str(error))
        if not connected or not self._local_alive(candidate):
            return self._disconnected()
        now = time.monotonic()
        if now >= self._deadline:
            self.timeout()
        if self._connected_at is None:
            self._connected_at = now
        return now - self._connected_at >= _STABILITY_SECONDS

    def _candidate(self, pid: int | None, before: int | None) -> int | None:
        if self._pid is not None and pid != self._pid:
            self._lost("exited")
        if pid is None or pid == before:
            return None
        self._pid = pid
        return pid

    def _remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.timeout()
        return remaining

    def timeout(self) -> NoReturn:
        """Explain which startup witness never became stable."""
        reason = "never connected to Hub with the new PID"
        if self._connected_at is not None:
            reason = "did not complete the Hub connection stability window"
        self._fail(f"display did not come back within {self._wait:g}s: {reason}")

    def _local_alive(self, pid: int) -> bool:
        return self._paths.is_running() and self._paths.peer_pid() == pid

    def _disconnected(self) -> bool:
        if self._connected_at is not None:
            self._lost("disconnected from Hub or lost its socket")
        return False

    def _lost(self, reason: str) -> NoReturn:
        phase = "before connecting to Hub"
        if self._connected_at is not None:
            phase = (
                f"after {time.monotonic() - self._connected_at:.1f}s connected to Hub"
            )
        self._fail(f"display pid {self._pid} {reason} {phase}")

    def _fail(self, message: str) -> NoReturn:
        message += self._stderr_tail()
        RestartReadiness.failure(self._spec, message)
        raise DisplayReadinessError(message)

    @staticmethod
    def _stderr_tail() -> str:
        path = Path.home() / ".punt-labs/lux/logs/luxd-display-stderr.log"
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 4096))
                tail = stream.read(4096).decode("utf-8", errors="replace")
        except OSError:
            return ""
        lines = tail.splitlines()[-12:]
        if not lines:
            return ""
        return "\nDisplay stderr (last 12 lines, at most 4096 bytes):\n" + "\n".join(
            lines
        )
