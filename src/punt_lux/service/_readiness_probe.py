"""The single budgeted local Display ownership witness."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Self

from punt_lux.socket_owner import SocketOwner

if TYPE_CHECKING:
    from punt_lux.service.display_paths import DisplayPaths


_LOCAL_PROBE_SECONDS = 0.5


class ReadinessProbe:
    """Readiness polls already retry; one poll must not retry past its budget."""

    _paths: DisplayPaths

    def __new__(cls, paths: DisplayPaths) -> Self:
        self = super().__new__(cls)
        self._paths = paths
        return self

    def local(self, pid: int, timeout: float) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(min(_LOCAL_PROBE_SECONDS, timeout))
                probe.connect(str(self._paths.socket_path))
                return SocketOwner.peer_pid_of(probe) == pid
        except OSError:
            return False
