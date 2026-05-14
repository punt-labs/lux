"""Socket path discovery and display process lifecycle helpers.

Shared between the display server and client — no ImGui dependency.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Self

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DisplayPaths — OO API for socket/pid/log path resolution and lifecycle
# ---------------------------------------------------------------------------


class DisplayPaths:
    """Resolve socket, PID, and log paths for a display server instance."""

    _socket_path: Path

    def __new__(cls, socket_path: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._socket_path = socket_path or cls._default_path()
        return self

    @staticmethod
    def _default_path() -> Path:
        """Return the default Unix domain socket path for the display server.

        Resolution order:
        1. ``$LUX_SOCKET`` environment variable
        2. ``$XDG_RUNTIME_DIR/lux/display.sock``
        3. ``/tmp/lux-$USER/display.sock``
        """
        env = os.environ.get("LUX_SOCKET")
        if env:
            return Path(env)

        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            return Path(xdg) / "lux" / "display.sock"

        user = os.environ.get("USER", "unknown")
        return Path(f"/tmp/lux-{user}/display.sock")  # noqa: S108

    @property
    def socket_path(self) -> Path:
        """Return the socket path."""
        return self._socket_path

    @property
    def pid_path(self) -> Path:
        """Return the PID file path for this socket."""
        return self._socket_path.with_suffix(".sock.pid")

    @property
    def log_path(self) -> Path:
        """Return the log file path for this socket."""
        return self._socket_path.with_suffix(".sock.log")

    def is_running(self) -> bool:
        """Check whether a display server is alive at the socket path."""
        pid_path = self.pid_path
        if not pid_path.exists():
            return False
        try:
            pid = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def cleanup_stale(self) -> None:
        """Remove socket and PID file if the owning process is dead."""
        if self.is_running():
            return
        if self._socket_path.exists() and self._socket_path.is_socket():
            self._socket_path.unlink(missing_ok=True)
        if self.pid_path.exists():
            self.pid_path.unlink(missing_ok=True)

    def ensure(self, timeout: float = 5.0) -> Path:
        """Ensure a display server is running, spawning one if needed.

        Returns the socket path.
        Raises ``RuntimeError`` if the display fails to start within *timeout*.
        """
        if self.is_running():
            return self._socket_path

        self.cleanup_stale()

        self._socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._socket_path.parent.chmod(0o700)
        log_file = self.log_path.open("w")
        cmd = [
            sys.executable,
            "-m",
            "punt_lux",
            "display",
            "--socket",
            str(self._socket_path),
        ]
        try:
            subprocess.Popen(  # noqa: S603
                cmd,
                start_new_session=True,
                stdout=log_file,
                stderr=log_file,
            )
        finally:
            log_file.close()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._socket_path.exists() and self.is_running():
                return self._socket_path
            time.sleep(0.1)

        msg = f"Display server failed to start within {timeout}s at {self._socket_path}"
        raise RuntimeError(msg)

    def write_pid(self) -> None:
        """Write the current process PID next to the socket file."""
        self.pid_path.write_text(str(os.getpid()))

    def remove_pid(self) -> None:
        """Remove the PID file for the socket path."""
        self.pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Hub path helpers — module-level functions for luxd (not display-server)
# ---------------------------------------------------------------------------


def hub_dir() -> Path:
    """Return the hub state directory: ~/.punt-labs/lux/"""
    return Path.home() / ".punt-labs" / "lux"


def hub_pid_path() -> Path:
    """Return the PID file path for luxd."""
    return hub_dir() / "hub.pid"


def hub_port_path() -> Path:
    """Return the port file path for luxd."""
    return hub_dir() / "hub.port"


def hub_log_dir() -> Path:
    """Return the log directory for luxd."""
    return hub_dir() / "logs"


def read_hub_port() -> int | None:
    """Read the hub port from the port file. Returns None if not available."""
    path = hub_port_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError) as exc:
        logger.warning("Could not read hub port from %s: %s", path, exc)
        return None


def is_hub_running() -> bool:
    """Check whether luxd is running by reading its PID file."""
    pid_path = hub_pid_path()
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
