"""Nonblocking local daemon startup; the detached owner outlives its Display."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Self

from punt_lux.terminal.runtime_directory import RuntimeDirectory

logger = logging.getLogger(__name__)

__all__ = ["DaemonLauncher"]


class DaemonLauncher:
    _path: Path
    _pid: int | None
    _next_attempt: float

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path.absolute()
        self._pid = None
        self._next_attempt = 0
        return self

    @property
    def child_pid(self) -> int | None:
        """A child started by this launcher, never inferred from a pid file."""
        return self._pid

    def ensure(self) -> None:
        """Start after connection failure, without waiting on the UI thread."""
        self._poll()
        if self._pid is not None or time.monotonic() < self._next_attempt:
            return
        self._next_attempt = time.monotonic() + 5
        RuntimeDirectory.prepare(self._path.parent)
        logger.info("Starting terminal daemon subprocess")
        null = os.open(os.devnull, os.O_RDWR)
        try:
            self._pid = os.posix_spawn(
                sys.executable,
                self._argv(),
                dict(os.environ),
                file_actions=[(os.POSIX_SPAWN_DUP2, null, fd) for fd in range(3)],
            )
        finally:
            os.close(null)

    def _argv(self) -> list[str]:
        """Run the terminal daemon in the current Python environment."""
        return [sys.executable, "-m", "punt_lux.ptyd", "--socket", str(self._path)]

    def poll(self) -> None:
        self._poll()

    def _poll(self) -> None:
        if self._pid is None:
            return
        try:
            pid, _status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            pid = self._pid
        if pid:
            self._pid = None
