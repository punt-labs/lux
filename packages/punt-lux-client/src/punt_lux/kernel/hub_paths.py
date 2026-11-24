"""Hub (luxd) path resolution and liveness, symmetric to DisplayPaths.

Locates luxd's state directory and PID/port files, and
reports hub liveness from its PID file. The display-process counterpart
lives in ``service/display_paths.py``.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Self, final

from punt_lux.kernel.home_paths import LuxHome

logger = logging.getLogger(__name__)
_PORT_FILE = "hub.port"
_PID_FILE = "hub.pid"


@final
class HubPaths:
    """Resolve luxd state paths and report hub liveness from its PID file.

    All paths derive from a single ``_dir`` root — the mirror of DisplayPaths'
    socket root for the luxd process rather than the display process.
    """

    _dir: Path

    def __new__(cls, root: Path | None = None) -> Self:
        """Resolve metadata paths under the specified or default Hub root."""
        self = super().__new__(cls)
        self._dir = root or LuxHome.resolve().root
        return self

    @property
    def dir(self) -> Path:
        """Return the hub state directory, usually ``~/.punt-labs/lux/``."""
        return self._dir

    @property
    def pid_path(self) -> Path:
        """Return the PID file path for luxd."""
        return self._dir / _PID_FILE

    @property
    def port_path(self) -> Path:
        """Return the port file path for luxd."""
        return self._dir / _PORT_FILE

    def prepare(self) -> None:
        """Secure the Hub state directory before publishing runtime files."""
        self._dir = LuxHome(self._dir).prepare_root()

    # None return = port file absent/unwritten — genuine absence contract (PY-TS-14).
    def read_port(self) -> int | None:
        """Read the hub port from the port file, or None if not available."""
        try:
            with suppress(FileNotFoundError):
                return int((self._dir / _PORT_FILE).read_text().strip())
        except (ValueError, OSError):
            logger.warning("Could not read Hub port file")
        return None

    def is_running(self) -> bool:
        """Return whether luxd is running, per its PID file."""
        try:
            pid = int((self._dir / _PID_FILE).read_text().strip())
        except (ValueError, OSError):
            return False
        if pid <= 0:
            return False
        try:
            with suppress(PermissionError):
                os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
