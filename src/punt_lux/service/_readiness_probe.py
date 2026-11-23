"""The local ownership and remote Hub witnesses used by Display readiness."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from punt_lux.service._hub_display_probe import HubDisplayProbe
from punt_lux.socket_owner import SocketOwner

if TYPE_CHECKING:
    from punt_lux.service.display_paths import DisplayPaths


_LOCAL_PROBE_SECONDS = 0.5


class ReadinessProbe:
    """Readiness polls already retry; one poll must not retry past its budget."""

    @staticmethod
    def local(paths: DisplayPaths, pid: int, timeout: float) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(min(_LOCAL_PROBE_SECONDS, timeout))
                probe.connect(str(paths.socket_path))
                return SocketOwner.peer_pid_of(probe) == pid
        except OSError:
            return False

    @staticmethod
    def connected(pid: int, timeout: float) -> str | None:
        return HubDisplayProbe(pid, timeout).connected()
