"""Hub (luxd) path resolution and liveness helpers.

Distinct from the display-process lifecycle in ``paths.py``: these locate
luxd's state directory, PID/port files, and log directory, and read them.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


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
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
