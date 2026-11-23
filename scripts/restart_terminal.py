"""Restart the optional machine-local terminal daemon for `make restart`."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from punt_lux.kernel.logging_config import configure_logging
from punt_lux.kernel.socket_owner import SocketOwner
from punt_lux.service.terminal_service import TerminalService
from punt_service import ServiceActionFailedError, ServiceNotInstalledError

logger = logging.getLogger(__name__)
_WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.5


# The socket node can be absent between daemon instances.
def _socket_identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino


def _await_replacement(
    owner: SocketOwner,
    before: int | None,  # No prior peer credential was readable.
    path: Path,
    previous_socket: tuple[int, int] | None,  # No node existed before restart.
) -> bool:
    deadline = time.monotonic() + _WAIT_SECONDS
    pid: int | None = None  # No peer credential observed on the last poll.
    candidate: tuple[int, int] | None = None  # No node sampled on the last poll.
    while time.monotonic() < deadline:
        if before is not None:
            pid = owner.pid()
            if pid is not None and pid != before:
                return True
        else:
            candidate = _socket_identity(path)
            pid = None
            if candidate is not None and candidate != previous_socket:
                pid = owner.pid()
                if pid is not None and _socket_identity(path) == candidate:
                    return True
        time.sleep(_POLL_SECONDS)
    logger.error(
        "luxd-pty replacement not observed at %s "
        "(previous PID: %s, last PID: %s, previous node: %s, candidate node: %s)",
        path,
        before,
        pid,
        previous_socket,
        candidate,
    )
    return False


def main() -> int:
    """Restart the running PTY service without starting it on inactive machines."""
    configure_logging("lux", "cli")
    service = TerminalService()
    if not service.is_active:
        print("luxd-pty is not running; skipping restart.")
        return 0
    # The supervisor starts luxd-pty without overriding its default socket.
    path = Path.home() / ".punt-labs/lux/pty/luxd-pty.sock"
    owner = SocketOwner(path)
    # Retain the socket node as a witness if the old instance cannot answer.
    previous_socket = _socket_identity(path)
    before = owner.pid()
    print("Restarting luxd-pty ends its terminal sessions.", flush=True)
    try:
        result = service.restart()
    except (ServiceActionFailedError, ServiceNotInstalledError) as error:
        print(error, file=sys.stderr)
        return 1
    if not _await_replacement(owner, before, path, previous_socket):
        print(
            f"luxd-pty did not come back within {_WAIT_SECONDS:g}s. "
            "See ~/.punt-labs/lux/logs/lux.log for details.",
            file=sys.stderr,
        )
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
