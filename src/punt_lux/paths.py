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

logger = logging.getLogger(__name__)


def default_socket_path() -> Path:
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


def pid_file_path(socket_path: Path) -> Path:
    """Return the PID file path for a given socket path."""
    return socket_path.with_suffix(".sock.pid")


def log_file_path(socket_path: Path) -> Path:
    """Return the log file path for a given socket path."""
    return socket_path.with_suffix(".sock.log")


def is_display_running(socket_path: Path) -> bool:
    """Check whether a display server is alive at *socket_path*."""
    pid_path = pid_file_path(socket_path)
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


def cleanup_stale_socket(socket_path: Path) -> None:
    """Remove socket and PID file if the owning process is dead."""
    if is_display_running(socket_path):
        return
    if socket_path.exists() and socket_path.is_socket():
        socket_path.unlink(missing_ok=True)
    pid_path = pid_file_path(socket_path)
    if pid_path.exists():
        pid_path.unlink(missing_ok=True)


def ensure_display(socket_path: Path | None = None, timeout: float = 5.0) -> Path:
    """Ensure a display server is running, spawning one if needed.

    Returns the socket path (resolved default if *socket_path* was ``None``).
    Raises ``RuntimeError`` if the display fails to start within *timeout*.
    """
    if socket_path is None:
        socket_path = default_socket_path()

    if is_display_running(socket_path):
        return socket_path

    cleanup_stale_socket(socket_path)

    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    socket_path.parent.chmod(0o700)
    log_file = log_file_path(socket_path).open("w")
    try:
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "punt_lux", "display", "--socket", str(socket_path)],
            start_new_session=True,
            stdout=log_file,
            stderr=log_file,
        )
    finally:
        log_file.close()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path.exists() and is_display_running(socket_path):
            return socket_path
        time.sleep(0.1)

    msg = f"Display server failed to start within {timeout}s at {socket_path}"
    raise RuntimeError(msg)


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


def write_pid_file(socket_path: Path) -> None:
    """Write the current process PID next to the socket file."""
    pid_path = pid_file_path(socket_path)
    pid_path.write_text(str(os.getpid()))


def remove_pid_file(socket_path: Path) -> None:
    """Remove the PID file for the given socket path."""
    pid_file_path(socket_path).unlink(missing_ok=True)
