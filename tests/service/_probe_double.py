"""Deterministic local witness for restart tests using mocked Display paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.service._readiness_probe import ReadinessProbe


class ProbeDouble:
    """Keep PID/socket test setup independent of the real bounded socket probe."""

    @staticmethod
    def local(probe: ReadinessProbe, pid: int, _timeout: float) -> bool:
        return bool(probe._paths.is_running() and probe._paths.peer_pid() == pid)
