"""Connection creation contract with lazy, detached daemon startup."""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Self

from punt_lux.terminal.connection import TerminalConnection as TerminalConnection
from punt_lux.terminal.launcher import DaemonLauncher

__all__ = ["LocalConnector", "TerminalConnection"]


class LocalConnector:
    _path: Path
    _launcher: DaemonLauncher

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._launcher = DaemonLauncher(path)
        return self

    def open(self) -> TerminalConnection:
        self._launcher.poll()
        try:
            return TerminalConnection(self._path)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ECONNREFUSED):
                self._launcher.ensure()
            raise

    def poll(self) -> None:
        """Reap an exited startup contender, never stop a running daemon."""
        self._launcher.poll()
