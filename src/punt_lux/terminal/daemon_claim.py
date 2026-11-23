"""Lifetime OS claim acquired before socket cleanup/bind, never a PID heuristic."""

from __future__ import annotations

import fcntl
import os
import socket
import stat
from pathlib import Path
from typing import Self

from punt_lux.kernel.credentials import PeerCredentials
from punt_lux.terminal.runtime_directory import RuntimeDirectory


class DaemonBusyError(OSError):
    """Another daemon owns the claim or an existing listener."""


class DaemonClaim:
    _fd: int
    _closed: bool

    def __new__(cls, path: Path) -> Self:
        RuntimeDirectory.prepare(path.parent)
        self = super().__new__(cls)
        self._closed = False
        self._fd = os.open(
            str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            cls._check_file(self._fd)
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DaemonBusyError("terminal daemon already claimed") from error
            cls._clear_stale(path)
        except BaseException:
            self.close()
            raise
        return self

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._fd)
        # Never unlink the reusable lock inode: another waiter may have it open.

    @staticmethod
    def _check_file(fd: int) -> None:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("unsafe daemon lock file")
        if info.st_mode & 0o077 or info.st_nlink != 1:
            raise PermissionError(
                "daemon lock file must be private and unlinked elsewhere"
            )

    @staticmethod
    def _clear_stale(path: Path) -> None:
        try:
            original = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(original.st_mode) or original.st_uid != os.getuid():
            raise PermissionError("refusing to remove non-socket or foreign endpoint")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.05)
            try:
                probe.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                pass
            else:
                PeerCredentials.require_same_user(probe)
                raise DaemonBusyError("terminal listener already running")
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise OSError("endpoint changed during stale cleanup")
        path.unlink()
