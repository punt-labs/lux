"""Deterministic local witness for restart tests using mocked Display paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unittest.mock import MagicMock


class ProbeDouble:
    """Keep PID/socket test setup independent of the real bounded socket probe."""

    @staticmethod
    def local(paths: MagicMock, pid: int, _timeout: float) -> bool:
        return bool(paths.is_running() and paths.peer_pid() == pid)
