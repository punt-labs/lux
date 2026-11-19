"""Nonblocking local daemon startup; the detached owner outlives its Display."""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path
from typing import Self

from punt_lux.terminal.runtime_directory import RuntimeDirectory


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
        log = self._open_log()
        try:
            null = os.open(os.devnull, os.O_RDONLY)
            try:
                actions = [
                    (os.POSIX_SPAWN_DUP2, null, 0),
                    (os.POSIX_SPAWN_DUP2, log, 1),
                    (os.POSIX_SPAWN_DUP2, log, 2),
                ]
                argv = [
                    sys.executable,
                    "-m",
                    "punt_lux.ptyd",
                    "--socket",
                    str(self._path),
                ]
                self._pid = os.posix_spawn(
                    sys.executable,
                    argv,
                    dict(os.environ),
                    file_actions=actions,
                )
            finally:
                os.close(null)
        finally:
            os.close(log)

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

    def _open_log(self) -> int:
        path = Path(str(self._path) + ".log")
        fd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        info = os.fstat(fd)
        if (
            info.st_uid != os.getuid()
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
        ):
            os.close(fd)
            raise PermissionError("daemon log must be a private regular file")
        return fd
