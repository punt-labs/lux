"""Hub (luxd) path resolution and liveness, symmetric to DisplayPaths.

Locates luxd's state directory, PID/port files, and log directory, and
reports hub liveness from its PID file. The display-process counterpart
lives in ``paths.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Self, final

logger = logging.getLogger(__name__)


@final
class HubPaths:
    """Resolve luxd state paths and report hub liveness from its PID file.

    All paths derive from a single ``_dir`` root — the mirror of DisplayPaths'
    socket root for the luxd process rather than the display process.
    """

    _dir: Path

    def __new__(cls, root: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._dir = root or Path.home() / ".punt-labs" / "lux"
        return self

    @property
    def dir(self) -> Path:
        """Return the hub state directory: ~/.punt-labs/lux/"""
        return self._dir

    @property
    def pid_path(self) -> Path:
        """Return the PID file path for luxd."""
        return self._dir / "hub.pid"

    @property
    def port_path(self) -> Path:
        """Return the port file path for luxd."""
        return self._dir / "hub.port"

    @property
    def log_dir(self) -> Path:
        """Return the log directory for luxd."""
        return self._dir / "logs"

    # None return = port file absent/unwritten — genuine absence contract (PY-TS-14).
    def read_port(self) -> int | None:
        """Read the hub port from the port file, or None if not available."""
        path = self.port_path
        if not path.exists():
            return None
        try:
            return int(path.read_text().strip())
        except (ValueError, OSError) as exc:
            logger.warning("Could not read hub port from %s: %s", path, exc)
            return None

    def is_running(self) -> bool:
        """Return whether luxd is running, per its PID file."""
        pid_path = self.pid_path
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
